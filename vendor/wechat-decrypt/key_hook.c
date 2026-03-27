/*
 * key_hook.c — Injectable dylib for extracting WeChat SQLCipher keys.
 *
 * Runs INSIDE WeChat's process via DYLD_INSERT_LIBRARIES, so it uses
 * mach_task_self() instead of task_for_pid(). No SIP changes needed.
 *
 * Build:
 *   cc -shared -O2 -o key_hook.dylib key_hook.c
 *
 * Usage:
 *   DYLD_INSERT_LIBRARIES=./key_hook.dylib /Applications/WeChat.app/Contents/MacOS/WeChat
 *
 * Output: /tmp/wechat_all_keys.json
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>

#define MAX_KEYS 256
#define HEX_PATTERN_LEN 96
#define CHUNK_SIZE (2 * 1024 * 1024)
#define OUTPUT_FILE "/tmp/wechat_all_keys.json"
#define SIGNAL_FILE "/tmp/wechat_keys_done"
#define DELAY_SECONDS 20

typedef struct {
    char key_hex[65];
    char salt_hex[33];
    char full_pragma[100];
} key_entry_t;

static int is_hex(unsigned char c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}

static void to_lower(char *s) {
    for (; *s; s++)
        if (*s >= 'A' && *s <= 'F') *s += 32;
}

static void *scan_thread(void *arg) {
    (void)arg;
    sleep(DELAY_SECONDS);

    fprintf(stderr, "[key_hook] Scanning own memory for SQLCipher keys...\n");

    task_t task = mach_task_self();
    key_entry_t keys[MAX_KEYS];
    int key_count = 0;
    size_t total = 0;

    mach_vm_address_t addr = 0;
    while (1) {
        mach_vm_size_t size = 0;
        vm_region_basic_info_data_64_t info;
        mach_msg_type_number_t info_count = VM_REGION_BASIC_INFO_COUNT_64;
        mach_port_t obj;

        kern_return_t kr = mach_vm_region(task, &addr, &size,
            VM_REGION_BASIC_INFO_64, (vm_region_info_t)&info, &info_count, &obj);
        if (kr != KERN_SUCCESS) break;
        if (size == 0) { addr++; continue; }

        if ((info.protection & (VM_PROT_READ | VM_PROT_WRITE)) ==
            (VM_PROT_READ | VM_PROT_WRITE))
        {
            mach_vm_address_t ca = addr;
            while (ca < addr + size) {
                mach_vm_size_t cs = addr + size - ca;
                if (cs > CHUNK_SIZE) cs = CHUNK_SIZE;

                vm_offset_t data;
                mach_msg_type_number_t dc;
                kr = mach_vm_read(task, ca, cs, &data, &dc);
                if (kr == KERN_SUCCESS) {
                    unsigned char *buf = (unsigned char *)data;
                    total += dc;

                    for (size_t i = 0; i + HEX_PATTERN_LEN + 3 < dc; i++) {
                        if (buf[i] != 'x' || buf[i+1] != '\'') continue;

                        int valid = 1;
                        for (int j = 0; j < HEX_PATTERN_LEN; j++) {
                            if (!is_hex(buf[i+2+j])) { valid = 0; break; }
                        }
                        if (!valid || buf[i+2+HEX_PATTERN_LEN] != '\'') continue;

                        char kh[65], sh[33];
                        memcpy(kh, buf+i+2, 64);    kh[64] = 0;
                        memcpy(sh, buf+i+2+64, 32);  sh[32] = 0;
                        to_lower(kh);
                        to_lower(sh);

                        int dup = 0;
                        for (int k = 0; k < key_count; k++) {
                            if (strcmp(keys[k].key_hex, kh) == 0 &&
                                strcmp(keys[k].salt_hex, sh) == 0) { dup = 1; break; }
                        }
                        if (dup || key_count >= MAX_KEYS) continue;

                        strcpy(keys[key_count].key_hex, kh);
                        strcpy(keys[key_count].salt_hex, sh);
                        snprintf(keys[key_count].full_pragma, 100,
                            "x'%s%s'", kh, sh);
                        key_count++;
                    }
                    mach_vm_deallocate(task, data, dc);
                }
                ca += cs;
            }
        }
        addr += size;
    }

    fprintf(stderr, "[key_hook] Scanned %.1f MB, found %d unique keys\n",
            total / (1024.0 * 1024.0), key_count);

    FILE *f = fopen(OUTPUT_FILE, "w");
    if (f) {
        fprintf(f, "{\n");
        for (int i = 0; i < key_count; i++) {
            fprintf(f, "  \"%s\": \"%s\"%s\n",
                    keys[i].salt_hex, keys[i].full_pragma,
                    i < key_count - 1 ? "," : "");
        }
        fprintf(f, "}\n");
        fclose(f);
        fprintf(stderr, "[key_hook] Keys written to %s\n", OUTPUT_FILE);
    }

    FILE *sig = fopen(SIGNAL_FILE, "w");
    if (sig) { fprintf(sig, "%d\n", key_count); fclose(sig); }

    return NULL;
}

__attribute__((constructor))
static void hook_init(void) {
    fprintf(stderr, "[key_hook] Loaded. Will scan memory in %d seconds...\n", DELAY_SECONDS);
    pthread_t tid;
    pthread_create(&tid, NULL, scan_thread, NULL);
    pthread_detach(tid);
}
