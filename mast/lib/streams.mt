import "unittest" =~ [=> unittest]
import "lib/enum" =~ [=> makeEnum :DeepFrozen]
exports (
    Sink, Source, Pump,
    makeSink, makeSource, makePump,
    flow,
    alterSink, alterSource,
)

# A new stream library.

interface Sink :DeepFrozen:
    "A receptacle into which discrete packets of data may be deposited."

    to run(packet) :Vow[Void]:
        "Receive `packet`, returning a `Vow` which resolves when the sink is
         ready to receive again."

    to complete() :Vow[Void]:
        "Signal that no more packets will be delivered, returning a `Vow`
         which resolves when the sink has released its resources."

    to abort(problem) :Vow[Void]:
        "Signal that no more packets will be delivered because of `problem`,
         returning a `Vow` which resolves when the sink has released its
         resources."

interface Source :DeepFrozen:
    "A source from which discrete packets of data are delivered."

    to run(sink :Sink) :Vow[Void]:
        "Deliver a packet to `sink` at a later time.

         Returns a `Vow` which resolves after attempted delivery, either to
         `null` in case of success, or a broken promise in case of failure."

object makeSink as DeepFrozen:
    "A maker of several types of sinks."

    to asList() :Pair[Vow[List], Sink]:
        def l := [].diverge()
        def [p, r] := Ref.promise()

        object listSink as Sink:
            to run(packet) :Void:
                l.push(packet)

            to complete() :Void:
                r.resolve(l.snapshot())

            to abort(problem) :Void:
                r.smash(problem)

        return [p, listSink]

def testMakeSinkAsList(assert):
    def [l, sink] := makeSink.asList()
    return when (sink(1), sink(2), sink(3)) ->
        when (sink.complete()) ->
            assert.willEqual(l, [1, 2, 3])

def testMakeSinkAsListAbort(assert):
    def [l, sink] := makeSink.asList()
    return when (sink(1), sink(2), sink(3)) ->
        when (sink.abort("Testing")) ->
            assert.willBreak(l)

unittest([
    testMakeSinkAsList,
    testMakeSinkAsListAbort,
])

object makeSource as DeepFrozen:
    "A maker of several types of sources."

    to fromIterator(iter) :Source:
        return def iterSource(sink :Sink) :Vow[Void] as Source:
            return try:
                escape ej:
                    sink(iter.next(ej))
                catch _:
                    sink.complete()
            catch problem:
                sink.abort(problem)

    to fromIterable(iter) :Source:
        return makeSource.fromIterator(iter._makeIterator())

def testMakeSourceFromIterable(assert):
    def [l, sink] := makeSink.asList()
    def source := makeSource.fromIterable([1, 2, 3])
    # One extra turn is required for completion to be delivered.
    for _ in (0..3):
        source(sink)
    return assert.willEqual(l, [[0, 1], [1, 2], [2, 3]])

unittest([testMakeSourceFromIterable])

def flow(source, sink) :Vow[Void] as DeepFrozen:
    "Flow all packets from `source` to `sink`, returning a `Vow` which
     resolves to `null` upon completion or a broken promise upon failure."

    def [p, r] := Ref.promise()

    object flowSink as Sink:
        to run(packet) :Vow[Void]:
            # We must pass the packet to the sink, and not request another
            # packet until we have completed delivery. However, we will cause
            # a deep recursion on the promises if we return `source(flowSink)`
            # directly. Instead, we return `null` as soon as delivery of
            # *this* packet has finished. ~ C.
            return when (sink(packet)) ->
                source<-(flowSink)
                null

        to complete() :Vow[Void]:
            r.resolve(null)
            return sink.complete()

        to abort(problem) :Vow[Void]:
            r.smash(problem)
            return sink.abort(problem)

    source<-(flowSink)
    return p

def testFlow(assert):
    def [l, sink] := makeSink.asList()
    def source := makeSource.fromIterable([1, 2, 3])
    return when (flow(source, sink)) ->
        assert.willEqual(l, [[0, 1], [1, 2], [2, 3]])

unittest([testFlow])

interface Pump :DeepFrozen:
    "A machine which emits zero or more packets for every incoming packet."

    to run(packet) :List:
        "Consume `packet` and return zero or more packets."

def [PumpState :DeepFrozen,
     QUIET :DeepFrozen,
     PACKETS :DeepFrozen,
     SINKS :DeepFrozen,
     CLOSING :DeepFrozen,
     FINISHED :DeepFrozen,
     ABORTED :DeepFrozen,
] := makeEnum(["quiet", "packets", "sinks", "closing", "finished", "aborted"])

def pumpPair(pump :Pump) :Pair[Sink, Source] as DeepFrozen:
    "Given `pump`, produce a sink which feeds packets into the pump and a
     source which produces the pump's results."

    # The current state enum and the actual state variable.
    var ps :PumpState := QUIET
    # QUIET, FINISHED: null; PACKETS, CLOSING: list of packets; SINKS: list of
    # sinks; ABORTED: problem
    var state := null

    def pumpSource(sink :Sink) :Vow[Void] as Source:
        return switch (ps):
            match ==QUIET:
                def [p, r] := Ref.promise()
                ps := SINKS
                state := [[sink, r]]
                p
            match ==PACKETS:
                def [packet] + packets := state
                if (packets.size() == 0):
                    ps := QUIET
                    state := null
                else:
                    state := packets
                sink<-(packet)
            match ==SINKS:
                def [p, r] := Ref.promise()
                state with= ([sink, r])
                p
            match ==CLOSING:
                def [packet] + packets := state
                if (packets.size() == 0):
                    ps := FINISHED
                    state := null
                else:
                    state := packets
                sink<-(packet)
            match ==FINISHED:
                sink<-complete()
            match ==ABORTED:
                sink<-abort(state)

    object pumpSink as Sink:
        to run(packet) :Vow[Void]:
            return switch (ps):
                match ==QUIET:
                    ps := PACKETS
                    state := pump(packet)
                    null
                match ==PACKETS:
                    state add= (pump(packet))
                    null
                match ==SINKS:
                    def [[sink, r]] + sinks := state
                    r.resolve(null)
                    if (sinks.size() == 0):
                        ps := QUIET
                        state := null
                    else:
                        state := sinks
                    sink<-(packet)

        to complete() :Void:
            switch (ps):
                match ==QUIET:
                    ps := FINISHED
                match ==PACKETS:
                    ps := CLOSING
                match ==SINKS:
                    ps := FINISHED
                    for [sink, r] in (state):
                        sink<-complete()
                        r.resolve(null)
                    state := null

        to abort(problem) :Void:
            if (ps == SINKS):
                for [sink, r] in (state):
                    sink<-abort(problem)
                    r.smash(problem)
            ps := ABORTED
            state := problem

    return [pumpSink, pumpSource]

object makePump as DeepFrozen:
    "A maker of several types of pumps."

    to id() :Pump:
        "The identity pump."

        return def idPump(packet) :List as Pump:
            return [packet]

    to filter(predicate) :Pump:
        return def filterPump(packet) :List as Pump:
            return if (predicate(packet)) { [packet] } else { [] }

    to scan(f, var z) :Pump:
        var first :Bool := true
        return def scanPump(packet) :List as Pump:
            return if (first):
                first := false
                # Sorry! ~ C.
                [z, z := f(z, packet)]
            else:
                # Okay, clearly not so sorry. ~ C.
                [z := f(z, packet)]

def testMakePumpId(assert):
    def pump := makePump.id()
    var l := []
    for x in (0..4):
        l += pump(x)
    assert.equal(l, [0, 1, 2, 3, 4])

def testMakePumpFilter(assert):
    def pump := makePump.filter(fn x { x % 2 == 1 })
    var l := []
    for x in (0..5):
        l += pump(x)
    assert.equal(l, [1, 3, 5])

def testMakePumpScan(assert):
    def pump := makePump.scan(fn z, x { z + x }, 0)
    var l := []
    for x in (1..4):
        l += pump(x)
    assert.equal(l, [0, 1, 3, 6, 10])

def testPumpPairSingle(assert):
    def [sink, source] := pumpPair(makePump.id())
    def [p, r] := Ref.promise()
    object testSink as Sink:
        to run(packet):
            assert.equal(packet, 42)
        to complete():
            r.resolve(null)
        to abort(problem):
            r.smash(problem)
    flow(source, testSink)
    sink(42)
    sink.complete()
    return p

def testPumpPairPostHoc(assert):
    def [sink, source] := pumpPair(makePump.id())
    def [p, r] := Ref.promise()
    object testSink as Sink:
        to run(packet):
            assert.fail(`Didn't expect packet $packet`)
        to complete():
            r.resolve(null)
        to abort(problem):
            r.smash(problem)
    flow(source, testSink)
    sink.complete()
    return p

unittest([
    testMakePumpId,
    testMakePumpFilter,
    testMakePumpScan,
    testPumpPairSingle,
    testPumpPairPostHoc,
])

object alterSink as DeepFrozen:
    "A collection of decorative attachments for sinks."

    to map(f, sink :Sink) :Sink:
        "Map over packets coming into `sink` with the function `f`."

        return object mapSink extends sink as Sink:
            to run(packet) :Vow[Void]:
                return sink(f(packet))

    to filter(predicate, sink :Sink) :Sink:
        "Filter packets coming into `sink` with the `predicate`."

        def [filterSink, source] := pumpPair(makePump.filter(predicate))
        flow(source, sink)
        return filterSink

    to scan(f, z, sink :Sink) :Sink:
        "Accumulate a partial fold of `f` with `z` as the starting value."

        def [scanSink, source] := pumpPair(makePump.scan(f, z))
        flow(source, sink)
        return scanSink

def testAlterSinkMap(assert):
    def [l, sink] := makeSink.asList()
    def mapSink := alterSink.map(fn x { x + 1 }, sink)
    mapSink(1)
    mapSink(2)
    mapSink.complete()
    return assert.willEqual(l, [2, 3])

def testAlterSinkFilter(assert):
    def [l, sink] := makeSink.asList()
    def filterSink := alterSink.filter(fn x { x % 2 == 0 }, sink)
    for i in (0..4):
        filterSink(i)
    filterSink.complete()
    return assert.willEqual(l, [0, 2, 4])

def testAlterSinkScan(assert):
    def [l, sink] := makeSink.asList()
    def scanSink := alterSink.scan(fn z, x { z + x }, 0, sink)
    for i in (1..5):
        scanSink(i)
    scanSink.complete()
    return assert.willEqual(l, [0, 1, 3, 6, 10, 15])

unittest([
    testAlterSinkMap,
    testAlterSinkFilter,
    testAlterSinkScan,
])

object alterSource as DeepFrozen:
    "A collection of decorative attachments for sources."

    to map(f, source :Source) :Source:
        "Map over packets coming out of `source` with the function `f`."

        return def mapSource(sink :Sink) :Vow[Void] as Source:
            return source(alterSink.map(f, sink))

    to filter(predicate, source :Source) :Source:
        "Filter packets coming out of `source` with `predicate`."

        def [filterSink, filterSource] := pumpPair(makePump.filter(predicate))
        return def filteringSource(sink :Sink) :Vow[Void] as Source:
            return when (source(filterSink), filterSource(sink)) -> { null }

    to scan(f, z, source) :Source:
        "Produce partial folds of `source` with function `f` and initial value
         `z`."

        def [scanSink, scanSource] := pumpPair(makePump.scan(f, z))
        return def scanningSource(sink :Sink) :Vow[Void] as Source:
            return when (source(scanSink), scanSource(sink)) -> { null }

def testAlterSourceMap(assert):
    def [l, sink] := makeSink.asList()
    def source := makeSource.fromIterable([1, 2, 3])
    def mapSource := alterSource.map(fn [_, snd] { snd }, source)
    return when (flow(mapSource, sink)) ->
        assert.willEqual(l, [1, 2, 3])

def testAlterSourceFilter(assert):
    def [l, sink] := makeSink.asList()
    def source := makeSource.fromIterable([0, 1, 2, 3, 4])
    def filterSource := alterSource.filter(fn [_, x] { x % 2 == 0 }, source)
    return when (flow(filterSource, sink)) ->
        assert.willEqual(l, [0, 2, 4])

unittest([testAlterSourceMap, testAlterSourceFilter])