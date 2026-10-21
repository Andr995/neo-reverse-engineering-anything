/* Local verification fixture. MIT, same license as REA Desktop.
 * Both formats are analyzed statically; no target is executed by the tests.
 */
#ifdef WINDOWS_FIXTURE
#define ABI __attribute__((ms_abi))
#else
#define ABI
#endif

__attribute__((noinline)) ABI int calculate_score(int value)
{
    return value > 10 ? value * 3 + 7 : value + 42;
}

ABI int entry(void)
{
    return calculate_score(12);
}
