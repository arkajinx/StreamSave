# Verification — StreamSave 2.0

Checked on 12 October 2026.

## Passed

- Complete Python suite: **71 passed**.
- Dashboard DOM suite: **3 passed** (stale-link response, video/audio job flow, upstream error).
- Locked production dependency versions were installed and exercised. uv pip check reported compatible installed packages.
- Python syntax, JavaScript syntax, shell script syntax, JSON configuration and local documentation links.
- Official pinned Cobalt 11.7.1 dependencies installed using pnpm 9.6.0. pnpm deploy produced a runtime package, which started successfully with its original Git metadata.
- The combined launcher started both Cobalt and StreamSave, returned /api/health=200, served the creator credit/source offer and accepted HEAD /.
- Terminating the launcher stopped the services and returned exit code 0.
- Actual HTTP streaming of generated, owned MP4 and MP3 fixtures through the Cobalt API contract and the full StreamSave inspection → job → file flow.
- Unknown-length streams, missing Content-Type, oversized output, cancellation, unexpected tunnels/redirects, bounded JSON, error codes, session isolation, expiry and queue/storage limits.
- A full FFprobe packet scan rejects a truncated fragmented MP4 that a metadata-only probe accepted.
- Source offer excludes environment files, media, hidden subtree files and nested JSON/YAML runtime data.
- Independent code review found two important validation/source-offer issues; both received failing regressions and fixes.

## Live YouTube result

Using the user's video https://www.youtube.com/watch?v=nirgaVY3iuI:

- Cobalt's metadata/preparation request returned a valid tunnel response (one measured preflight took 8.28 seconds).
- The StreamSave dashboard inspection endpoint also returned 200 with the new backend.
- **A completed live YouTube file was not obtained.** MP3 tunnel trials returned no complete media output. A bounded diagnostic with system FFmpeg reported invalid input data.
- The application correctly marked these jobs failed and did not offer an invalid file as a successful download.

This confirms the Cobalt integration and metadata path, but not successful YouTube media access from a production host. Test both inspection and a saved, playable file on the selected host before sharing the website. An API/health success is not a YouTube test.

## Limits

- No Docker daemon is available in this workspace, so the complete Docker image has **not** been built here. The pinned Cobalt install/deploy/native runtime were checked. GitHub CI includes an image build and readiness/source-offer smoke test for after upload.
- No deployment was created on Railway, Render or another hosting provider, and no GitHub repository was pushed.
- Windows/macOS native setup was documented but not executed.
- Production traffic, resource capacity and paid/free host eligibility were not benchmarked or guaranteed.
- The optional freebind native package reported a sandbox filesystem build warning during installation. It is not enabled/used by this project; Cobalt API startup succeeded.
