Your focus: timing and state.
Look for races between async calls that can finish in either order, stale state read after an await, effects that run twice or after unmount, writes that land after a reset or sign-out and revive old state, retries that duplicate work, and clocks, time zones or expiry checks that are off by one or compare the wrong values.
