# Copyright (C) 2015 Google Inc. All rights reserved.
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


import "lib/enum" =~ [=> makeEnum]
import "lib/codec/utf8" =~ [=> UTF8 :DeepFrozen]
import "lib/streams" =~ [
    => Sink :DeepFrozen,
    => alterSink :DeepFrozen,
    => flow :DeepFrozen,
    => makePump :DeepFrozen,
]

exports (makeAMPServer, makeAMPClient)

# Either we await a key length, value length, or string.
def [AMPState :DeepFrozen,
     KEY :DeepFrozen,
     VALUE :DeepFrozen,
     STRING :DeepFrozen
] := makeEnum(["AMP key length", "AMP value length", "AMP string"])

def makeAMPPacketMachine() as DeepFrozen:
    var packetMap :Map := [].asMap()
    var pendingKey :Str := ""
    var results :List := []

    return object AMPPacketMachine:
        to getStateGuard():
            return AMPState

        to getInitialState():
            return [KEY, 2]

        to advance(state :AMPState, data):
            switch (state):
                match ==KEY:
                    # We have two bytes of data representing key length.
                    # Except the first byte is always 0x00.
                    def len := data[1]
                    # If the length was zero, then it was the end-of-packet
                    # marker. Go ahead and snip the packet.
                    if (len == 0):
                        results with= (packetMap)
                        packetMap := [].asMap()
                        return [KEY, 2]

                    # Otherwise, get the actual key string.
                    return [STRING, len]
                match ==VALUE:
                    # Same as the KEY case, but without EOP.
                    def len := (data[0] << 8) | data[1]
                    return [STRING, len]
                match ==STRING:
                    # First, decode.
                    def s := UTF8.decode(_makeBytes.fromInts(data), null)
                    # Was this for a key or a value? We'll guess based on
                    # whether there's a pending key.
                    if (pendingKey == ""):
                        # This was a key.
                        pendingKey := s
                        return [VALUE, 2]
                    else:
                        # This was a value.
                        packetMap with= (pendingKey, s)
                        pendingKey := ""
                        return [KEY, 2]

        to results():
            return results


def packAMPPacket(packet :Map[Str, Str]) :Bytes as DeepFrozen:
    var buf := []
    for via (UTF8.encode) key => via (UTF8.encode) value in (packet):
        def keySize :(Int <= 0xff) := key.size()
        buf += [0x00, keySize]
        buf += _makeList.fromIterable(key)
        def valueSize :(Int <= 0xffff) := value.size()
        buf += [valueSize >> 8, valueSize & 0xff]
        buf += _makeList.fromIterable(value)
    buf += [0x00, 0x00]
    return _makeBytes.fromInts(buf)


def makeAMP(sink, handler) as DeepFrozen:
    var serial :Int := 0
    var pending := [].asMap()

    def process(box):
        # Either it's a new command, a successful reply, or a failure.
        switch (box):
            match [=> _command] | var arguments:
                # New command.
                def _answer := if (arguments.contains("_ask")) {
                    def [=> _ask] | args := arguments
                    arguments := args
                    _ask
                } else {null}
                def result := handler<-(_command, arguments)
                if (serial != null):
                    when (result) ->
                        def packet := result | [=> _answer]
                        sink<-(packAMPPacket(packet))
                    catch _error_description:
                        def packet := result | [=> _answer,
                                                => _error_description]
                        sink<-(packAMPPacket(packet))
            match [=> _answer] | arguments:
                # Successful reply.
                def answer := _makeInt.fromBytes(_answer)
                if (pending.contains(answer)):
                    pending[answer].resolve(arguments)
                    pending without= (answer)
            match [=> _error] | arguments:
                # Error reply.
                def error := _makeInt(_error)
                if (pending.contains(error)):
                    def [=> _error_description := "unknown error"] | _ := arguments
                    pending[error].smash(_error_description)
                    pending without= (error)
            match _:
                pass

    return object AMP:
        to sink() :Sink:
            def AMPSink(box) as Sink:
                return when (process<-(box)) -> { null }
            def boxPump := makePump.fromStateMachine(makeAMPPacketMachine())
            return alterSink.withPump(boxPump, AMPSink)

        to send(command :Str, var arguments :Map, expectReply :Bool):
            if (expectReply):
                arguments |= ["_command" => command, "_ask" => `$serial`]
                def [p, r] := Ref.promise()
                pending |= [serial => r]
                serial += 1
                sink<-(packAMPPacket(arguments))
                return p
            else:
                sink<-(packAMPPacket(arguments))


def makeAMPServer(endpoint) as DeepFrozen:
    return object AMPServerEndpoint:
        to listenStream(handler):
            def f(source, sink):
                def amp := makeAMP(sink, handler)
                flow(source, amp.sink())
            endpoint.listenStream(f)


def makeAMPClient(endpoint) as DeepFrozen:
    return object AMPClientEndpoint:
        to connectStream(handler):
            return when (def [source, sink] := endpoint.connectStream()) ->
                def amp := makeAMP(sink, handler)
                flow(source, amp.sink())
