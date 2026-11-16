# Sample direct simulator run

This sanitized sample summarizes a real BootLab matrix invocation on the pinned MCUboot source with the committed BootLab simulator extension. It contains no host paths, raw logs, signing keys, or private evidence material.

**Observed run:** 6 scenario definitions, 6 passed, 0 failed, 0 skipped. Each row executed the exact Rust test `bootlab_direct_image` once. The run archived immutable image inputs and recorded their SHA-256 hashes.

| ID | Declared version | Selected image | Observed version | Cut reached | Candidate input SHA-256 | Selected primary SHA-256 | Input hashes matched |
|---|---:|---|---:|---:|---|---|---|
| D01 | 2.0.0 | candidate | 2.0.0+0 | false | `1de1b64b9172a9130172155cdd4c8b4f0044866a507ac0a23b3d880d141bc8f7` | `1de1b64b9172a9130172155cdd4c8b4f0044866a507ac0a23b3d880d141bc8f7` | true |
| D02 | 1.0.0 | primary | 1.0.0+0 | false | `70bc4346cea8a64f017a3f01217f5f605fb1de401010ea38e50c1416bf69e3e3` | `17fad28031f62e9387192209692db64f034a2c3ccb10a386f3048e61c1f38920` | true |
| D03 | 1.0.0 | primary | 1.0.0+0 | false | `5975067ae9ec5d74492ad2577025a211288f18299bfa025f6d65c7cff6809871` | `17fad28031f62e9387192209692db64f034a2c3ccb10a386f3048e61c1f38920` | true |
| D06 | 2.0.0 | candidate | 2.0.0+0 | true | `1de1b64b9172a9130172155cdd4c8b4f0044866a507ac0a23b3d880d141bc8f7` | `1de1b64b9172a9130172155cdd4c8b4f0044866a507ac0a23b3d880d141bc8f7` | true |
| V01 | 2.0.0 | primary | 2.0.0+0 | false | `48c239a78155153eca3a938f310f1387bd677c2e2d23aef6bd2a38f7d361f4e4` | `fb627999772a2cbb059525bd3c6941f3bf5e1c6e3bfb59e2700c4c3728183424` | true |
| V02 | 1.5.0 | candidate | 1.5.0+0 | false | `48c239a78155153eca3a938f310f1387bd677c2e2d23aef6bd2a38f7d361f4e4` | `48c239a78155153eca3a938f310f1387bd677c2e2d23aef6bd2a38f7d361f4e4` | true |

D01 observed the trusted v2.0.0 candidate selected. D02 and D03 observed the original trusted image selected after candidate payload mutation and untrusted signing, respectively. V01 and V02 used the identical trusted v1.5 candidate with downgrade prevention enabled and disabled; the enabled case selected v2.0.0, while the disabled control selected v1.5.0. D06 records that the requested interruption was reached and the simulator recovered to an allowed selection.

The observation is MCUboot bootloader image selection in the nrf52840 simulator layout (`primary=0x8000`, `secondary=0x3c000`, 8-byte alignment, erased value `0xff`). It does not execute application code and does not represent hardware testing. The signed evidence archive retains the complete records, logs, and immutable input bytes.
