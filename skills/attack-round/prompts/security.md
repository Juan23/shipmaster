Your focus: security and sign-in.
Look for checks that fail open: an error, a timeout, a missing value or a rejected promise that leaves a user signed in, a gate passed, or data shown when it should be refused. Also look for missing permission checks at the server, secrets in logs or responses, trust in client-supplied values, and sessions that outlive a revoked user, device or PIN.
