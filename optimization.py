"""optimization.py

(C) 2022 Egor Sanin <egordotsaninatgmaildotcom>
This local module is used in GarminCustomMap to find an optimized tile size
based on the following inputs: maximum tile size, maximum allowed number of
tiles, and the full extent in pixels of the input image.
For an in-depth discussion of this code and the algorithms visit
github.com/esan0/tiling_optimization
"""

import math
from itertools import combinations

import numpy as np


def optimize_dtb(x, y, max_tile_size, max_num_tiles):
    """This method uses brute force to find optimal tiles sizes of a full-extent image.

    This method contains several improvements to a basic brute force approach.
    We use of dtypes to reduce computational and memory load.
    We also use boolean indexing to sift out sections of the solution space that
    fall outside our input parameters.
    """

    # Set up solution space
    W, H = np.meshgrid(
        np.arange(1, x + 1, dtype=np.uint32), np.arange(1, y + 1, dtype=np.uint32)
    )
    Z = np.zeros((y, x), dtype=np.float32)
    img_ext = x * y

    # Tile size
    A = W * H
    # Calculate the side ratio
    S = np.minimum(W, H) / np.maximum(W, H)
    # Number of tiles, rows x columns
    N = (np.ceil(x / W) * np.ceil(y / H)).astype(np.uint32)
    # Pixel remainder shifted by 1 to avoid division by 0
    P = A * N - img_ext + 1
    # Mask the values that fall outside the constraints
    m = (A <= max_tile_size) & (N <= max_num_tiles)

    # Optimization score
    Z[m] = A[m] * S[m] / (N[m] * P[m])

    # Find optimal size
    opt_tile_size = np.unravel_index(np.argmax(Z), Z.shape)

    return (W[opt_tile_size], H[opt_tile_size])


def trial_division(n):
    """This is a trial division factorization implementation.

    This trial division factorization algorithm is taken from Wikipedia:
    https://en.wikipedia.org/wiki/Trial_division
    Additional lines added to get a sorted list of all factors of n including
    1 and n.
    """

    a = []
    while n % 2 == 0:
        a.append(2)
        n //= 2
    f = 3
    while f * f <= n:
        if n % f == 0:
            a.append(f)
            n //= f
        else:
            f += 2
    if n != 1:
        a.append(n)

    b = []
    for i in range(1, len(a) + 1):
        b += [math.prod(x) for x in combinations(a, i)]

    b = [x for x in set(b)]
    b.append(1)
    b.sort()

    return b


def optimize_fac(x, y, max_tile_size, max_num_tiles):
    """This method uses factoring to find optimal tiles sizes of a full-extent image.

    If factorization doesn't result in suitable tile size, then the dtb method
    is called in order to find an an imperfect solution with trailing pixels.
    """

    # Check if the image extent is smaller than the maximum tile size
    img_ext = x * y
    if max_tile_size >= img_ext:
        return (x, y)

    # Get all the factors of x and y
    w = np.array(trial_division(x), dtype=np.uint32)
    h = np.array(trial_division(y), dtype=np.uint32)

    # Set up solution space
    W, H = np.meshgrid(w, h)
    Z = np.zeros_like(W, dtype=np.float32)

    # Tile size
    A = W * H
    # Calculate the side ratio
    S = np.minimum(W, H) / np.maximum(W, H)
    # Number of tiles, rows x columns
    N = (np.ceil(x / W) * np.ceil(y / H)).astype(np.uint32)
    # Mask the values that fall outside the constraints
    m = (A <= max_tile_size) & (N <= max_num_tiles)

    # Optimization score
    Z[m] = A[m] * S[m] / N[m]

    # Check to see if we found anything, run dtb if not
    if not Z.any():
        return optimize_dtb(x, y, max_tile_size, max_num_tiles)

    # Find optimal size
    opt_tile_size = np.unravel_index(np.argmax(Z), Z.shape)

    return (W[opt_tile_size], H[opt_tile_size])
