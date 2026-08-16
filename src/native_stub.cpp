#ifdef NATIVE_BUILD
// The native env is test-only; give it a program entry point so `pio run`
// succeeds. Compiled out of firmware builds (NATIVE_BUILD undefined there).
int main() { return 0; }
#endif
