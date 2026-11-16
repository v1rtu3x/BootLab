# Optional Zephyr integration lane

[Project overview](../README.md) · [Visual walkthrough](../WALKTHROUGH.md) · [Documentation map](README.md)

**The intended outcome is a signed Zephyr application booting through MCUboot with an observable version marker. This lane is not yet validated end to end on a board.** The host matrix does not require Zephyr or hardware.

## 01 / What is in the repository

| File | Role |
|---|---|
| [src/main.c](../app/zephyr_version_demo/src/main.c) | Prints the demo name and `BUILD_VERSION` |
| [CMakeLists.txt](../app/zephyr_version_demo/CMakeLists.txt) | Builds the application and defines the marker |
| [prj.conf](../app/zephyr_version_demo/prj.conf) | Enables MCUboot integration, binary/hex output, and header padding |
| [sysbuild.conf](../app/zephyr_version_demo/sysbuild.conf) | Selects MCUboot in sysbuild |

A Zephyr workspace, SDK/toolchain, supported board, and working partition configuration are external prerequisites. The example below assumes a local workspace at `zephyr-work/`; adjust it to your installation.

## 02 / Build flow and current blocker

```mermaid
flowchart LR
    A["Application + version"] --> S["Zephyr sysbuild"]
    S --> B["MCUboot + signed image"]
    B --> F["Board flash layout"]
    F --> U["Flash + reset + UART capture"]
    classDef step fill:#12354e,color:#f4f1e8,stroke:#e7b26b;
    class A,S,B,F,U step;
```

The current `native_sim` configuration has an unresolved overlap in HEX output addresses. Validate the flash map for your selected board/configuration before using this application; a successful host matrix does not validate that layout.

## 03 / Board build template

From `BootLab/`, after preparing a Zephyr workspace and exporting its environment:

```bash
export ZEPHYR_BASE="$(pwd)/zephyr-work/zephyr"
west build -b nrf52840dk/nrf52840 --sysbuild app/zephyr_version_demo \
  -d build/zephyr_version_demo \
  -- -Dzephyr_version_demo_BUILD_VERSION=1.0.0+dev
```

This is an **unvalidated board-build template**, not a recorded successful build. The sysbuild-prefixed CMake argument targets the `zephyr_version_demo` application image. Confirm that the selected Zephyr revision propagates it and that the generated compile definition contains the intended value. The CMake file supplies its own string quoting; the version value does not need escaped quotation marks.

## 04 / Read a board result

1. Pin the Zephyr revision and toolchain and retain the final board/partition configuration.
2. Build MCUboot and the signed application successfully with a development key.
3. Flash a supported device and capture the boot log plus `BUILD_VERSION` output.
4. Exercise update, confirmation/revert where supported, invalid-image rejection, and reset recovery.
5. Tie each observation to board identity, image hashes, signing configuration, and retained logs.

An application banner proves that this application ran in that experiment. Establishing secure boot also requires evidence of the bootloader's configured verification and rejection behavior.

Use [the application README](../app/zephyr_version_demo/README.md) for the expected marker and [evidence limitations](LIMITATIONS.md) when interpreting a result.
