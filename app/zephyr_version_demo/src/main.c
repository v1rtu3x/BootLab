/*
 * Copyright (c) 2026 BootLab contributors
 * SPDX-License-Identifier: Apache-2.0
 */

#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

/* BUILD_VERSION is expected to be passed via CMAKE extra flags. */
#ifndef BUILD_VERSION
#define BUILD_VERSION "unknown"
#endif

int main(void)
{
    printk("BootLab Zephyr version demo\n");
    printk("BUILD_VERSION=%s\n", BUILD_VERSION);
    return 0;
}
