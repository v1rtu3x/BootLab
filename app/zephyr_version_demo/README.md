# Zephyr version demo application

[Project overview](../../README.md) · [Visual walkthrough](../../WALKTHROUGH.md) · [Documentation map](../../docs/README.md)

**This small application prints a build marker to identify the firmware that ran.** It is an optional example; the host-side BootLab matrix does not need Zephyr or hardware.

## 01 / What each file does

| File | Purpose |
|---|---|
| [src/main.c](src/main.c) | Prints the application name and `BUILD_VERSION`, then returns |
| [CMakeLists.txt](CMakeLists.txt) | Adds the source and a string-valued build-version definition |
| [prj.conf](prj.conf) | Enables printk, MCUboot integration, binary/HEX output, and header padding |
| [sysbuild.conf](sysbuild.conf) | Requests MCUboot as part of sysbuild |

```text
build-version input -> application image -> MCUboot boot -> UART marker
        intent             signed bytes       decision       observation
```

The application does not download updates, mark a trial image confirmed, provision keys, or collect structured BootLab evidence. Those capabilities need separate implementation in a board runner/application.

## 02 / Build template

Prepare a compatible Zephyr workspace and SDK, export its environment, and select a board with a reviewed MCUboot flash layout. From `BootLab/`:

```bash
west build -b nrf52840dk/nrf52840 --sysbuild app/zephyr_version_demo \
  -d build/zephyr_version_demo \
  -- -Dzephyr_version_demo_BUILD_VERSION=1.0.0+dev
```

This is an **unvalidated board-build template**. The image-prefixed CMake argument is intended for the `zephyr_version_demo` sysbuild image; check its generated configuration and compile definition with your selected Zephyr revision. CMake supplies the string quoting, so do not add literal escaped quotes around the version.

The current `native_sim` configuration has an unresolved overlap in generated HEX addresses. Read [the integration notes](../../docs/ZEPHYR_INTEGRATION.md) before adapting the configuration. A different board name alone is not evidence that its partitions and signing setup are correct.

## 03 / Expected application output

If the marker reaches the compilation correctly and the resulting app runs, it prints:

```text
BootLab Zephyr version demo
BUILD_VERSION=1.0.0+dev
```

This is an expected example, not a captured board result. Retain the actual build command, board/partition configuration, image hash, and UART capture. Check the bootloader's configured verification and negative-case behavior separately before making a secure-boot claim.

## 04 / Interpret the result

Use [the integration guide](../../docs/ZEPHYR_INTEGRATION.md) to retain board, build, and runtime observations. See [evidence boundaries](../../docs/LIMITATIONS.md) for what the existing host matrix establishes.
