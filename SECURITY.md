# Security

Kolibre is built to run **on a home network**, behind a router that does not forward a port
to it. That assumption is not a disclaimer at the bottom of the page: it is the premise that
makes the rest of this file readable. Everything below is written so that you can decide for
yourself whether your situation matches it.

## Reporting a problem

Open a [GitHub issue](https://github.com/GottiPaolo/Kolibre/issues).

If what you found could be used against someone before it is fixed, **do not put the details
in a public issue**. Open one that says only that you have found something and how to reach
you, and the details can move somewhere private.

There is no bounty and no SLA. This is one person's project; what I can promise is that I
will read it and answer.

## What is protected

- **Every API route requires authentication**, except the handful listed below.
- **Passwords are stored as bcrypt hashes**, never in reversible form.
- **The signing key for sessions is generated on first run** — 32 random bytes written to
  `DATA_DIR/secret_key` with mode `0600` — and the server refuses to start with a known
  placeholder value, including one passed through the environment.
- **Devices authenticate with their own token** (`kolibre_tok_…`), not with your session.
  Rotating `SECRET_KEY` logs out browsers but does **not** break device sync.
- **Library permissions are per library and per user**: read, edit, share, manage, delete.
  Both the read gate and the write gate run on the server, not in the interface.
- **Covers, author photos and uploaded files require credentials**, including when the
  browser loads them as plain images.
- **URLs you paste are resolved before they are fetched**, and refused if they point inside
  your own network — private, loopback, link-local or otherwise reserved addresses. Redirects
  are followed by hand and re-checked at every hop.

## What is not protected, deliberately

These are known. They are listed because a gap you know about is a decision, and a gap you
do not know about is a surprise.

- **There is no rate limiting on login**, and failed attempts are not logged. On a home
  network that is a trade; on the open internet it is not.
- **You can tell whether a username exists by how long the server takes to answer.** A real
  username costs a bcrypt verification (~235 ms); a non-existent one returns almost
  immediately. Nothing is done to equalise the two.
- **A few routes are open on purpose**, because a plugin has to reach them *before* it has
  any credentials: the server and frontend port (`/api/tools/server-port`,
  `/api/tools/frontend-port`) and the plugin version, manifest and file endpoints used for
  self-update.
- **There is no audit log.** `server.log` records activity, but it is a log, not a tamper
  evident record — and it is readable only by an administrator.
- **Sessions last seven days** and cannot be revoked individually. Changing `SECRET_KEY`
  invalidates all of them at once.

## If you want to expose it anyway

Put it behind a reverse proxy that terminates TLS and adds its own authentication — a
password in front of the whole thing, or a VPN, or a tunnel. Do not forward the port
directly.

## Reasonable expectations

Kolibre has no automated security testing and no external audit. The code was read end to
end before the first public release, and that pass found and fixed real problems — a path
that escaped the dictionaries folder, writes that only checked the read permission, a
server-side request that followed a URL anywhere. It is a reason to take this file as what
it is: an honest account, not a guarantee.
