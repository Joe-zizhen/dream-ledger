import time

t0 = time.perf_counter()


def is_prime(n):
    if n < 2:
        return False
    for i in range(2, n):
        if n % i == 0:
            return False
    return True


total = sum(1 for x in range(2, 8000) if is_prime(x))
print("primes:", total)
print("elapsed_ms: %d" % ((time.perf_counter() - t0) * 1000))
