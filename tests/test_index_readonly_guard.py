"""Static guard: the hourly index job is read-only (#258, kiwi rule: dry-run only, no tx).

Parses the index modules with `ast` (nothing is imported or run) and fails if they gain a way to
sign or send a transaction, a new Helius RPC method, a new outbound host, or a path that prints
the API key. A failure here means a reviewer must look, not that the change is wrong.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

MODULES = sorted(
    [p for p in (ROOT / "index").glob("*.py")]
    + [
        ROOT / "adapters" / f"{n}.py"
        for n in (
            "index_collect",
            "index_observe",
            "index_history_cache",
            "helius_client",
            "helius_parse",
            "market_data",
            "token2022",
            "hubs",
        )
    ]
    + [ROOT / "tools" / f"{n}.py" for n in ("run_index", "prune_index_cache", "index_watch")]
)
JOB_FILES = sorted((ROOT / "ops" / "index-job").iterdir())

FORBIDDEN_IMPORTS = ("solders.keypair", "solana.transaction", "nacl.signing", "solders.transaction")
FORBIDDEN_WORDS = (
    "sendtransaction",
    "sendrawtransaction",
    "simulatetransaction",
    "signtransaction",
    "requestairdrop",
    "keypair",
    "secret_key",
    "private_key",
    "mnemonic",
    "seed phrase",
    "seed_phrase",
)
# Read-only JSON-RPC / DAS methods the index uses today. A new one must be reviewed and added here.
RPC_ALLOWLIST = frozenset(
    {
        "getAsset",
        "getAccountInfo",
        "getTokenLargestAccounts",
        "getMultipleAccounts",
        "getTokenAccountsByOwner",
    }
)
HOSTS = frozenset({"mainnet.helius-rpc.com", "api.dexscreener.com"})
LOG_FUNCS = frozenset(
    {"print", "debug", "info", "warning", "error", "exception", "critical", "write"}
)


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _id(path: Path) -> str:
    return str(path.relative_to(ROOT))


def test_module_list_exists() -> None:
    missing = [_id(p) for p in MODULES if not p.is_file()]
    assert not missing, f"guarded modules moved or renamed, update this test: {missing}"
    assert len(MODULES) >= 15


@pytest.mark.parametrize("path", MODULES, ids=_id)
def test_no_signing_imports(path: Path) -> None:
    bad = []
    for node in ast.walk(_tree(path)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        bad += [n for n in names if any(n == f or n.startswith(f + ".") for f in FORBIDDEN_IMPORTS)]
    assert not bad, f"{_id(path)} imports signing code: {bad}"


@pytest.mark.parametrize("path", MODULES, ids=_id)
def test_no_signing_words(path: Path) -> None:
    hits = []
    for node in ast.walk(_tree(path)):
        text = None
        if isinstance(node, ast.Name):
            text = node.id
        elif isinstance(node, ast.Attribute):
            text = node.attr
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        elif isinstance(node, ast.alias):
            text = node.name
        if text and any(w in text.lower() for w in FORBIDDEN_WORDS):
            hits.append((getattr(node, "lineno", "?"), text[:60]))
    assert not hits, f"{_id(path)} mentions signing/key material: {hits}"


@pytest.mark.parametrize("path", JOB_FILES, ids=_id)
def test_job_files_do_not_sign(path: Path) -> None:
    low = path.read_text(encoding="utf-8").lower()
    for w in (*FORBIDDEN_WORDS, "solana transfer", "spl-token transfer", "solana-keygen"):
        assert w not in low, f"{_id(path)} contains {w!r}"


def _rpc_methods() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in MODULES:
        for node in ast.walk(_tree(path)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "rpc" or not node.args:
                continue
            first = node.args[0]
            name = first.value if isinstance(first, ast.Constant) else f"<dynamic@{node.lineno}>"
            found.setdefault(str(name), []).append(_id(path))
    return found


def test_rpc_methods_are_allowlisted() -> None:
    found = _rpc_methods()
    assert found, "no .rpc() calls found: the scan is broken"
    new = {m: where for m, where in found.items() if m not in RPC_ALLOWLIST}
    assert not new, f"RPC methods outside the read-only allowlist (review, then add): {new}"


def test_helius_client_hosts_and_das_methods() -> None:
    tree = _tree(ROOT / "adapters" / "helius_client.py")
    consts: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in ("_HOSTS", "_DAS_METHODS"):
                arg = node.value.args[0]
                consts[target.id] = {e.value for e in arg.elts}  # type: ignore[attr-defined]
    assert consts["_HOSTS"] == HOSTS, "outbound host list changed: review it"
    assert consts["_DAS_METHODS"] <= {"getAsset", "getAssetBatch"}
    for node in ast.walk(tree):
        is_str = isinstance(node, ast.Constant) and isinstance(node.value, str)
        if is_str and node.value.startswith(("http://", "https://")):
            host = node.value.split("/")[2]
            assert host in HOSTS, f"URL to an unlisted host: {node.value}"


def _mentions_key(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and "key" in sub.id.lower():
            return True
        if isinstance(sub, ast.Attribute) and (sub.attr == "_key" or sub.attr == "environ"):
            return True
        if isinstance(sub, ast.Call) and getattr(sub.func, "attr", None) == "getenv":
            return True
    return False


@pytest.mark.parametrize("path", MODULES, ids=_id)
def test_api_key_never_logged(path: Path) -> None:
    bad = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if name in LOG_FUNCS and any(_mentions_key(a) for a in node.args):
                bad.append(node.lineno)
        is_repr = isinstance(node, ast.FunctionDef) and node.name in ("__repr__", "__str__")
        if is_repr and any(_mentions_key(r) for r in ast.walk(node) if isinstance(r, ast.Return)):
            bad.append(node.lineno)
    assert not bad, f"{_id(path)} may print the API key at lines {bad}"


def test_api_key_read_only_from_environ() -> None:
    reads = []
    for path in MODULES:
        tree = _tree(path)
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "HELIUS_API_KEY":
                parent = parents.get(node)
                ok = (
                    isinstance(parent, ast.Call)
                    and isinstance(parent.func, ast.Attribute)
                    and parent.func.attr in ("get", "getenv")
                    and ast.unparse(parent.func.value) in ("os.environ", "os")
                ) or (
                    isinstance(parent, ast.Subscript) and ast.unparse(parent.value) == "os.environ"
                )
                assert ok, f"{_id(path)}:{node.lineno} uses HELIUS_API_KEY outside os.environ"
                reads.append(_id(path))
    assert reads == ["tools/run_index.py"], f"HELIUS_API_KEY read in unexpected places: {reads}"
