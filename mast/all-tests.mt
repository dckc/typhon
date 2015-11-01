def bench(_, _) as DeepFrozen:
    return null

import.script("lib/atoi")
import.script("lib/cache")
import.script("lib/codec/utf8")
import.script("lib/continued", [=> &&bench])
import.script("lib/entropy/pool")
import("lib/enum", [=> unittest])
# Needs fake Timer.
# import.script("lib/irc/client")
import.script("lib/irc/user")
import.script("lib/monte/monte_optimizer")
import.script("lib/netstring")
import.script("lib/parsers/html")
## Depends on derp, not in the repo.
# import.script("lib/parsers/http")
import.script("lib/parsers/marley", [=> &&bench])
import.script("lib/paths")
import.script("lib/percent")
import("lib/record", [=> unittest])
import.script("lib/singleUse")
import.script("lib/slow/exp", [=> &&bench])
import.script("lib/words")
import.script("fun/elements")
import.script("tests/auditors")
import.script("tests/fail-arg")
import.script("tests/lexer")
import.script("tests/parser")
import.script("tests/expander")
import("tools/infer", [=> unittest])
