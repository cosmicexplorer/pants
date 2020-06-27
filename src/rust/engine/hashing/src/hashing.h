/* Generated with cbindgen:0.8.7 */

#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

#define FINGERPRINT_SIZE 32

typedef struct {
  uint8_t _0[FINGERPRINT_SIZE];
} Fingerprint;

/**
 * A Digest is a fingerprint, as well as the size in bytes of the plaintext for which that is the
 * fingerprint.
 * It is equivalent to a Bazel Remote Execution Digest, but without the overhead (and awkward API)
 * of needing to create an entire protobuf to pass around the two fields.
 */
typedef struct {
  Fingerprint _0;
  uintptr_t _1;
} Digest;

void _throwaway_for_cbindgen_debug_info(Fingerprint _fp, Digest _d);
