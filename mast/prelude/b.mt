# Copyright (C) 2014 Google Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
exports (::"b``")

object bytePattern as DeepFrozen:
    pass

object byteValue as DeepFrozen:
    pass


object ::"b``" as DeepFrozen:
    "A quasiparser for `Bytes`.

     This object behaves like `simple__quasiParser`; it takes some textual
     descriptions of bytes and returns a bytestring. It can interpolate
     objects which coerce to `Bytes` and `Str`.

     As a pattern, this object performs slicing of bytestrings. Semantics
     mirror `simple__quasiParser` with respect to concatenated patterns and
     greediness."

    to patternHole(index):
        return [bytePattern, index]

    to valueHole(index):
        return [byteValue, index]

    to matchMaker(pieces):
        # Filter out empty pieces. Sometimes the compiler generates them,
        # especially at the tail end, and it messes up pattern matching.
        def chunks :DeepFrozen := [for piece in (pieces) ? (piece != "") piece]

        return object byteMatcher as DeepFrozen:
            to matchBind(values, specimen, ej):
                # The strategy: Lay down "railroad" segments one at a time,
                # matching against the specimen.
                # XXX var position :(0..!specimen.size()) exit ej := 0
                var position :Int := 0
                var inPattern :Bool := false
                def patterns := [].diverge()
                var patternMarker := 0

                for var chunk in (chunks):
                    if (chunk =~ [==bytePattern, index]):
                        if (inPattern):
                            throw.eject(ej,
                                "Can't catenate patterns with patterns!")
                        inPattern := true
                        patternMarker := position

                        continue

                    if (chunk =~ [==byteValue, index]):
                        chunk := values[index]
                    else:
                        chunk := _makeBytes.fromStr(chunk)

                    def len := chunk.size()
                    if (inPattern):
                        # Before we look for a match, let's double-check that
                        # finding a match is possible with a length check.
                        if (position + len > specimen.size()):
                            throw.eject(ej, "Specimen too short")

                        # Let's go find a match, and then slice off a pattern.
                        while (specimen.slice(position, position + len) != chunk):
                            position += 1
                            if (position >= specimen.size()):
                                throw.eject(ej, "Length mismatch")

                        # Found a match! Mark the pattern, then jump ahead.
                        patterns.push(specimen.slice(patternMarker, position))
                        position += len
                        inPattern := false

                    else:
                        if (specimen.slice(position, position + len) == chunk):
                            position += len
                        else:
                            throw.eject(ej, "Couldn't match literal/value")

                if (inPattern):
                    # The final piece was a pattern.
                    patterns.push(specimen.slice(patternMarker,
                                                 specimen.size()))
                else:
                    # The final piece was a value. Make sure that we're not
                    # behind; if we are, it's usually because our specimen had
                    # too many characters.
                    if (specimen.size() > position):
                        throw.eject(ej, "Specimen too long")

                return patterns.snapshot()

    to valueMaker(pieces):
        def chunks :DeepFrozen := [for piece in (pieces)
            if (piece =~ s :Str) { _makeBytes.fromStr(s) } else { piece }]

        return object bytes as DeepFrozen:
            to substitute(values) :Bytes:
                var rv := _makeBytes.fromInts([])
                for chunk in (chunks):
                    switch (chunk):
                        match [==byteValue, index]:
                            switch (values[index]):
                                match s :Str:
                                    rv += _makeBytes.fromStr(s)
                                match bs :Bytes:
                                    rv += bs
                        match bs :Bytes:
                            rv += bs
                return rv
