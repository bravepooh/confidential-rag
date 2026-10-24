# Security architecture

Threat model: the system holds recordings and transcripts of identifiable
couples in therapy. Under Israeli privacy law (תיקון 13) and GDPR-equivalent
regimes this is special-category health data. A breach is not an embarrassment,
it is a clinical and legal event.

Self-hosting the model closes the obvious hole (no AI vendor reads the
sessions). It does not close the other two, which are how data gets **in** and
how it gets **out**.

## The two doors

### Intake: not Telegram

Telegram bot uploads are not end-to-end encrypted and files are stored on
Telegram's servers. Sending an hour of a couple's session through a bot puts
that recording on infrastructure in another jurisdiction belonging to a company
we have no agreement with. That single hop undoes every other control here.

**Instead:** a minimal upload page served by the box and reachable only over
**Tailscale**. Her phone joins the private WireGuard network; the upload goes
device to box with no third party and no public port. From her side it is a
bookmark on the home screen.

### Archive: encrypt before Drive

Plaintext transcripts in Google Drive means Google holds readable clinical
records. **rclone crypt** encrypts contents and filenames on the box before
upload, so Drive is dumb offsite storage.

Tradeoff, to be decided with her explicitly: she can no longer browse sessions
inside Drive. The replacement is a browse page on the box (also Tailscale-only),
which is where she would read the guidance anyway.

## Controls

| Layer | Control |
|---|---|
| Network | No public listening ports. Tailscale only. Outbound blocked by default with a narrow allowlist, so a compromised dependency cannot exfiltrate |
| Models | Local open weights only. No API keys for any inference service exist on the box |
| Identity | Couples are pseudonymous codes (`couple-07`). The code-to-name map never lives on the server |
| Audio | Source recordings deleted automatically after successful transcription. Voices are the most identifying artefact and are not needed once transcribed |
| At rest | Full-disk encryption. On a rented server this needs remote unlock at boot (dropbear in initramfs); on a machine in the clinic it is FileVault and a checkbox |
| Access | Key-only SSH, no password auth, 2FA on the Tailscale account, single operator |
| Backup | Encrypted, versioned, restore tested |
| Audit | Every job and access logged, retained. Doubles as compliance evidence |
| Legal | Written consent from both partners covering recording and AI processing; DPIA on file |

## Why a machine in the clinic beats a rented server

Physical custody is itself a control. A Mac mini in her office with FileVault and
Tailscale has no datacenter, no hosting provider with hypervisor access, and no
disk that anyone else can pull. For this data class that is a materially
stronger answer than any rented box, and it is cheaper over any horizon longer
than four months.

## Repo boundary

The public method library is built on the laptop and committed. Her documents,
session audio, transcripts and generated guidance are gitignored at the root and
are only ever ingested on the private box. See the confidentiality block at the
top of `.gitignore`. Nothing in that block gets relaxed.
