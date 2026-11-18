# Server hardening — Ubuntu (Hetzner box)

For kiwi, to paste in Termius. Nobody from Claude runs these: this file only lists the commands (#342 B, #348 B2).
Each step has **Do**, **Verify** (what you should see) and **Rollback**. Go in order; stop at the first
surprise and paste the output in #1.

Golden rule for steps 1–2: **keep your current Termius session open** until a *new* session works.
If you lock yourself out anyway, use the Hetzner web console (Cloud Console → server → "Console", or
Robot → rescue for a dedicated box) and run the step's Rollback there.

| Step | What | Downtime |
|---|---|---|
| 0 | Preflight | none |
| 1 | SSH: keys only, no passwords | none |
| 2 | Firewall (ufw): only 22, 80, 443 in | none |
| 3 | fail2ban (bans SSH brute force) | none |
| 4 | unattended-upgrades (security updates) | none |
| 5 | System wallet key file: 600, owner `coinbot` | none |
| 6 | The pending reboot | ~1–2 min |

All commands work as `root` or as a sudo user (with `root`, `sudo` is harmless).

## 0. Preflight

```bash
lsb_release -ds; uname -r          # Ubuntu version and running kernel
whoami
sudo ss -tlnp                       # every TCP port that listens, with its program
```

**Verify:** note which ports listen. Expected: `22` (sshd), `80`/`443` (web server), and maybe services on
`127.0.0.1` only (those are not reachable from outside and need no rule). If anything else listens on
`0.0.0.0` or `[::]` and must stay reachable from the internet, stop and ask in #1 before step 2.

## 1. SSH: keys only, no passwords

**1a. Make sure your key works first.** In Termius: Keychain → Generate key (ED25519) → "Export to host"
for this server. Then check the server has it:

```bash
sudo cat ~/.ssh/authorized_keys | cut -c1-40     # shows the start of each public key only
```

Open a **second** Termius session to the server using the key (no password). It must log in.
Only if it does, go on. Leave both sessions open.

**1b. Do:**

```bash
sudo tee /etc/ssh/sshd_config.d/00-hardening.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin prohibit-password
EOF
sudo sshd -t && echo CONFIG-OK
sudo systemctl restart ssh
```

If `sshd -t` complains about `KbdInteractiveAuthentication` (old Ubuntu 20.04), replace that line with
`ChallengeResponseAuthentication no` and run `sshd -t` again. Do not restart until it prints `CONFIG-OK`.

The `00-` prefix matters: sshd keeps the first value it reads, so this file wins over
`50-cloud-init.conf` (which on Hetzner images often sets `PasswordAuthentication yes`).
Restarting `ssh` does not close sessions that are already open.

**Verify:**

```bash
sudo sshd -T | grep -Ei '^(passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication|permitrootlogin) '
ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password -o StrictHostKeyChecking=no localhost true
```

Expected: `passwordauthentication no`, `kbdinteractiveauthentication no`, `pubkeyauthentication yes`,
`permitrootlogin without-password` (same as prohibit-password); the second command ends with
`Permission denied (publickey).` Then open a **third** Termius session with the key: it must work.

**Rollback:**

```bash
sudo rm /etc/ssh/sshd_config.d/00-hardening.conf && sudo sshd -t && sudo systemctl restart ssh
```

## 2. Firewall (ufw): allow 22, 80, 443

**Do** (the allow rules come before `enable`, so SSH is never cut):

```bash
sudo apt-get install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
```

Outgoing stays open, so the bots still reach Helius, Jupiter and GitHub.

**Verify:**

```bash
sudo ufw status verbose
```

Expected: `Status: active`, `Default: deny (incoming), allow (outgoing)`, and `ALLOW IN` for `22/tcp`,
`80/tcp`, `443/tcp` (plus the same three with `(v6)`). Open a new Termius session: it must work. Open the
site in a browser: it must load.

Note: if Docker is installed (`which docker`), its published ports bypass ufw. Ask in #1 if it is.

**Rollback:**

```bash
sudo ufw disable
```

## 3. fail2ban

**Do:**

```bash
sudo apt-get update
sudo apt-get install -y fail2ban python3-systemd
sudo tee /etc/fail2ban/jail.local >/dev/null <<'EOF'
[sshd]
enabled  = true
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
EOF
sudo systemctl enable fail2ban
sudo systemctl restart fail2ban
```

**Verify:**

```bash
systemctl is-active fail2ban
sudo fail2ban-client status sshd
```

Expected: `active`, and a status block for jail `sshd` (`Currently banned` may already be above 0: the
internet scans every server).

If it ever bans you (5 wrong logins in 10 minutes), from the Hetzner console:
`sudo fail2ban-client set sshd unbanip <your IP>`.

**Rollback:**

```bash
sudo systemctl disable --now fail2ban && sudo rm /etc/fail2ban/jail.local
```

## 4. unattended-upgrades (security updates only)

**Do:**

```bash
sudo apt-get install -y unattended-upgrades
sudo tee /etc/apt/apt.conf.d/20auto-upgrades >/dev/null <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
```

Ubuntu's default `50unattended-upgrades` installs only security updates and does **not** reboot by itself
(`Automatic-Reboot "false"`). Keep it that way: a reboot in the middle of a bot run is worse than a reboot
by hand (step 6).

**Verify:**

```bash
apt-config dump | grep -E 'Periodic::(Update-Package-Lists|Unattended-Upgrade) '
apt-config dump | grep -E 'Unattended-Upgrade::Automatic-Reboot '
systemctl list-timers apt-daily-upgrade.timer --no-pager
sudo unattended-upgrade --dry-run 2>&1 | tail -3
```

Expected: both Periodic values `"1"`; `Automatic-Reboot "false"` (or no line, which means false); the timer
has a NEXT time; the dry run ends without an error.

**Rollback:**

```bash
sudo sed -i 's/"1"/"0"/' /etc/apt/apt.conf.d/20auto-upgrades
```

## 5. System wallet key file: mode 600, owner `coinbot`

Never `cat` this file. These commands show only its mode and owner.

**Verify first:**

```bash
id coinbot
sudo stat -c '%a %U:%G %n' /etc/coin/fee-bot /etc/coin/fee-bot/keypair.json /etc/coin/fee-bot/env
sudo find / -xdev \( -name '*keypair*.json' -o -name 'id.json' \) -not -path '/proc/*' 2>/dev/null
```

Expected:

```
700 coinbot:coinbot /etc/coin/fee-bot
600 coinbot:coinbot /etc/coin/fee-bot/keypair.json
600 coinbot:coinbot /etc/coin/fee-bot/env
```

and `find` lists only `/etc/coin/fee-bot/keypair.json` (plus devnet throwaway keys under
`~/.config/solana/devnet/`, if any). Any other copy of a mainnet key: **stop, do not delete it, write in #1.**
If `keypair.json` does not exist yet, the fee bot is not installed (#310): skip this step.

**Do, only if the mode or owner is wrong:**

```bash
sudo chown coinbot:coinbot /etc/coin/fee-bot /etc/coin/fee-bot/keypair.json /etc/coin/fee-bot/env
sudo chmod 700 /etc/coin/fee-bot
sudo chmod 600 /etc/coin/fee-bot/keypair.json /etc/coin/fee-bot/env
```

Then run the Verify block again.

**Rollback:** none needed. The bot refuses any other mode or owner, so the right values are the only ones
that work.

## 6. The pending reboot

Last, so it also loads everything installed above.

**Check it is needed:**

```bash
ls /var/run/reboot-required 2>/dev/null && cat /var/run/reboot-required.pkgs
```

**Pick a quiet minute.** Timers (UTC): fee bot `:20`, holder snapshot `:40`, payout `00:10`, index hourly,
sampler every 5 minutes. Good window: between `:50` and `:58`, not between 23:50 and 00:30 UTC.

```bash
systemctl list-timers 'coin-*' --no-pager
systemctl list-units 'coin-*' --state=activating --no-pager     # must list 0 units (nothing running now)
```

**Do:**

```bash
sudo reboot
```

Wait 1–2 minutes and reconnect with the key.

**Verify:**

```bash
uptime                                              # up a few minutes
uname -r                                            # new kernel if the reboot was for one
ls /var/run/reboot-required 2>/dev/null || echo NO-REBOOT-PENDING
systemctl list-timers 'coin-*' --no-pager           # same timers as before, with NEXT times
systemctl --failed --no-pager                       # 0 loaded units listed
sudo ufw status | head -1; systemctl is-active fail2ban ssh
```

Expected: `NO-REBOOT-PENDING`, the `coin-*` timers back, no failed units, `Status: active`, `active active`.
After the next `:00`, check the index still publishes (new file on the `index-data` branch).

**Rollback:** a reboot cannot be undone. If the server does not come back in 5 minutes, open the Hetzner
console: if the new kernel does not boot, choose "Advanced options" in GRUB and the previous kernel, then
write in #1.

## When done

Paste in #1 the output of:

```bash
sudo sshd -T | grep -Ei '^(passwordauthentication|permitrootlogin) '; sudo ufw status | head -1
systemctl is-active fail2ban; apt-config dump | grep 'Unattended-Upgrade "'
sudo stat -c '%a %U:%G %n' /etc/coin/fee-bot/keypair.json; ls /var/run/reboot-required 2>/dev/null || echo NO-REBOOT-PENDING
```

It shows settings only, no secrets.
