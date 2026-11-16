# Sample direct simulator results from full matrix

This sanitized sample is derived from the successful 35-definition run against a clean copy of the pinned MCUboot source with the committed BootLab patch applied. It includes no host paths, raw logs, signing keys, or private evidence material.

**Observed run:** 35 scenario definitions passed, 0 failed, 0 skipped. The six direct image cases below each executed `bootlab_direct_image` once and archived immutable image inputs with SHA-256 hashes.

| ID | Expected version | Selected image | Observed version | Cut reached | Candidate input SHA-256 | Observed candidate SHA-256 | Input hashes matched |
|---|---:|---|---:|---:|---|---|---|
| D01 | 2.0.0 | candidate | 2.0.0+0 | false | `25730f17454c50d4a6fd358b5813a3a547b9e18979ee036f7cce72c55b4e5acd` | `25730f17454c50d4a6fd358b5813a3a547b9e18979ee036f7cce72c55b4e5acd` | true |
| D02 | 1.0.0 | primary | 1.0.0+0 | false | `ce056bbdc40abc2e1b1f52461e294be744dc35067f375c5d7a334392b0205272` | `ce056bbdc40abc2e1b1f52461e294be744dc35067f375c5d7a334392b0205272` | true |
| D03 | 1.0.0 | primary | 1.0.0+0 | false | `682a58727cd5307d2d715f0f2e33ed52a782d18609781ecf91adbbb18c9de41f` | `682a58727cd5307d2d715f0f2e33ed52a782d18609781ecf91adbbb18c9de41f` | true |
| D06 | 2.0.0 | candidate | 2.0.0+0 | true | `25730f17454c50d4a6fd358b5813a3a547b9e18979ee036f7cce72c55b4e5acd` | `25730f17454c50d4a6fd358b5813a3a547b9e18979ee036f7cce72c55b4e5acd` | true |
| V01 | 2.0.0 | primary | 2.0.0+0 | false | `fb7551046cf3bcbbbc2b36bdbabca9cacc81dd0921fba598cd353da91786f060` | `fb7551046cf3bcbbbc2b36bdbabca9cacc81dd0921fba598cd353da91786f060` | true |
| V02 | 1.5.0 | candidate | 1.5.0+0 | false | `fb7551046cf3bcbbbc2b36bdbabca9cacc81dd0921fba598cd353da91786f060` | `fb7551046cf3bcbbbc2b36bdbabca9cacc81dd0921fba598cd353da91786f060` | true |

D01 selected the trusted v2.0.0 candidate. D02 and D03 retained the authenticated primary after payload modification and untrusted signing. V01 and V02 used the identical trusted v1.5 candidate; the downgrade-enabled case selected v2.0.0, while the disabled control selected v1.5.0. D06 reached its requested modeled interruption and recovered to an allowed selection.

These results observe MCUboot bootloader image selection in the modeled nrf52840 layout (`primary=0x8000`, `secondary=0x3c000`, 8-byte alignment, erased value `0xff`). They do not assert application execution or hardware behavior. Full case records and raw logs are retained in the run archive.
