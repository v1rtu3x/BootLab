# Sample direct simulator results from full matrix

This sanitized sample is derived from the successful 35-definition run against the pinned MCUboot source with the committed BootLab patch applied. The source run is `20261116T151901.887335Z-a4d8c1aa`; its per-case records and raw logs are retained in the signed portable evidence archive. This sample includes no host paths, raw logs, signing keys, or private evidence material.

**Observed run:** 35 scenario definitions passed, 0 failed, 0 skipped. The six direct image cases below each executed `bootlab_direct_image` once and archived immutable image inputs with SHA-256 hashes.

| ID | Expected version | Selected image | Observed version | Cut reached | Candidate input SHA-256 | Observed candidate SHA-256 | Input hashes matched |
|---|---:|---|---:|---:|---|---|---|
| D01 | 2.0.0 | candidate | 2.0.0+0 | false | `05e6718e2a752ad5368ad4223c88d95d253865299c37f14903c96aafa54b9cd3` | `05e6718e2a752ad5368ad4223c88d95d253865299c37f14903c96aafa54b9cd3` | true |
| D02 | 1.0.0 | primary | 1.0.0+0 | false | `4af5653fff67f188dae2afb1741d5ca89d48a5a630e84e65c2b5ecabcd373fd7` | `4af5653fff67f188dae2afb1741d5ca89d48a5a630e84e65c2b5ecabcd373fd7` | true |
| D03 | 1.0.0 | primary | 1.0.0+0 | false | `97eb85420158bd0308f2e0d758cf2e3a07162ed920e3a7fdd268d8738cbcf528` | `97eb85420158bd0308f2e0d758cf2e3a07162ed920e3a7fdd268d8738cbcf528` | true |
| D06 | 2.0.0 | candidate | 2.0.0+0 | true | `05e6718e2a752ad5368ad4223c88d95d253865299c37f14903c96aafa54b9cd3` | `05e6718e2a752ad5368ad4223c88d95d253865299c37f14903c96aafa54b9cd3` | true |
| V01 | 2.0.0 | primary | 2.0.0+0 | false | `5bce1ed408e13638d7d545dbdfc027b411719a1f8020dd205a07f49ce49abece` | `5bce1ed408e13638d7d545dbdfc027b411719a1f8020dd205a07f49ce49abece` | true |
| V02 | 1.5.0 | candidate | 1.5.0+0 | false | `5bce1ed408e13638d7d545dbdfc027b411719a1f8020dd205a07f49ce49abece` | `5bce1ed408e13638d7d545dbdfc027b411719a1f8020dd205a07f49ce49abece` | true |

D01 selected the trusted v2.0.0 candidate. D02 and D03 retained the authenticated primary after payload modification and untrusted signing. V01 and V02 used the identical trusted v1.5 candidate; the downgrade-enabled case selected v2.0.0, while the disabled control selected v1.5.0. D06 reached its requested modeled interruption and recovered to an allowed selection.

These results observe MCUboot bootloader image selection in the modeled nrf52840 layout (`primary=0x8000`, `secondary=0x3c000`, 8-byte alignment, erased value `0xff`). They do not assert application execution or hardware behavior. Full case records and raw logs are retained in the run archive.
