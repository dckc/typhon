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

from rpython.rlib.debug import debug_print
from rpython.rlib.objectmodel import we_are_translated
from rpython.rlib.rarithmetic import intmask

from typhon import ruv
from typhon.atoms import getAtom
from typhon.autohelp import autohelp, method
from typhon.errors import userError
from typhon.objects.collections.lists import wrapList, unwrapList
from typhon.objects.data import StrObject, unwrapBytes, unwrapInt
from typhon.objects.networking.streamcaps import StreamSink, StreamSource
from typhon.objects.networking.streams import StreamDrain, StreamFount
from typhon.objects.refs import LocalResolver, makePromise
from typhon.objects.root import Object, runnable
from typhon.vats import currentVat, scopedVat


RUN_1 = getAtom(u"run", 1)
RUN_2 = getAtom(u"run", 2)


def connectCB(connect, status):
    status = intmask(status)
    stream = connect.c_handle

    try:
        vat, resolvers = ruv.unstashStream(stream)
        fountResolver, drainResolver = unwrapList(resolvers)
        assert isinstance(fountResolver, LocalResolver)
        assert isinstance(drainResolver, LocalResolver)

        with scopedVat(vat):
            if status >= 0:
                debug_print("Made connection!")
                fountResolver.resolve(StreamFount(stream, vat))
                drainResolver.resolve(StreamDrain(stream, vat))
            else:
                error = "Connection failed: " + ruv.formatError(status)
                debug_print(error)
                fountResolver.smash(StrObject(error.decode("utf-8")))
                drainResolver.smash(StrObject(error.decode("utf-8")))
                # Done with stream.
                ruv.closeAndFree(stream)
    except:
        if not we_are_translated():
            raise

def connectStreamCB(connect, status):
    status = intmask(status)
    stream = connect.c_handle

    try:
        vat, resolvers = ruv.unstashStream(stream)
        sourceResolver, sinkResolver = unwrapList(resolvers)
        assert isinstance(sourceResolver, LocalResolver)
        assert isinstance(sinkResolver, LocalResolver)

        with scopedVat(vat):
            if status >= 0:
                debug_print("Made connection!")
                wrappedStream = ruv.wrapStream(stream, 2)
                sourceResolver.resolve(StreamSource(wrappedStream, vat))
                sinkResolver.resolve(StreamSink(wrappedStream, vat))
            else:
                error = "Connection failed: " + ruv.formatError(status)
                debug_print(error)
                sourceResolver.smash(StrObject(error.decode("utf-8")))
                sinkResolver.smash(StrObject(error.decode("utf-8")))
                # Done with stream.
                ruv.closeAndFree(stream)
    except:
        if not we_are_translated():
            raise


@autohelp
class TCP4ClientEndpoint(Object):
    """
    A TCPv4 client endpoint.
    """

    def __init__(self, host, port):
        self.host = host
        self.port = port

    def toString(self):
        return u"<endpoint (IPv4, TCP): %s:%d>" % (self.host.decode("utf-8"),
                                                   self.port)

    @method("List")
    def connect(self):
        vat = currentVat.get()
        stream = ruv.alloc_tcp(vat.uv_loop)

        fount, fountResolver = makePromise()
        drain, drainResolver = makePromise()

        # Ugh, the hax.
        resolvers = wrapList([fountResolver, drainResolver])
        ruv.stashStream(ruv.rffi.cast(ruv.stream_tp, stream),
                        (vat, resolvers))

        # Make the actual connection.
        ruv.tcpConnect(stream, self.host, self.port, connectCB)

        # Return the promises.
        return [fount, drain]

    @method("List")
    def connectStream(self):
        vat = currentVat.get()
        stream = ruv.alloc_tcp(vat.uv_loop)

        source, sourceResolver = makePromise()
        sink, sinkResolver = makePromise()

        # Ugh, the hax.
        resolvers = wrapList([sourceResolver, sinkResolver])
        ruv.stashStream(ruv.rffi.cast(ruv.stream_tp, stream),
                        (vat, resolvers))

        # Make the actual connection.
        ruv.tcpConnect(stream, self.host, self.port, connectStreamCB)

        # Return the promises.
        return [source, sink]


@runnable(RUN_2)
def makeTCP4ClientEndpoint(host, port):
    """
    Make a TCPv4 client endpoint.
    """

    host = unwrapBytes(host)
    port = unwrapInt(port)
    return TCP4ClientEndpoint(host, port)


def shutdownCB(shutdown, status):
    try:
        ruv.free(shutdown)
        # print "Shut down server, status", status
    except:
        if not we_are_translated():
            raise


@autohelp
class TCP4Server(Object):
    """
    A TCPv4 listening server.
    """

    listening = True

    def __init__(self, uv_server):
        self.uv_server = uv_server

    def toString(self):
        return u"<server (IPv4, TCP)>"

    @method("Void")
    def shutdown(self):
        if self.listening:
            shutdown = ruv.alloc_shutdown()
            ruv.shutdown(shutdown, ruv.rffi.cast(ruv.stream_tp,
                                                 self.uv_server),
                         shutdownCB)
            self.listening = False


def connectionCB(uv_server, status):
    status = intmask(status)

    # If the connection failed to complete, then whatever; we're a server, not
    # a client, and this is a pretty boring do-nothing failure mode.
    # XXX we *really* should have some way to report failures, though; right?
    if status < 0:
        return

    try:
        with ruv.unstashingStream(uv_server) as (vat, handler):
            uv_client = ruv.rffi.cast(ruv.stream_tp,
                                      ruv.alloc_tcp(vat.uv_loop))
            # Actually accept the connection.
            ruv.accept(uv_server, uv_client)
            # Incant the handler.
            from typhon.objects.collections.maps import EMPTY_MAP
            vat.sendOnly(handler, RUN_2, [StreamFount(uv_client, vat),
                                          StreamDrain(uv_client, vat)],
                         EMPTY_MAP)
    except:
        if not we_are_translated():
            raise

def connectionStreamCB(uv_server, status):
    status = intmask(status)

    # If the connection failed to complete, then whatever; we're a server, not
    # a client, and this is a pretty boring do-nothing failure mode.
    # XXX we *really* should have some way to report failures, though; right?
    if status < 0:
        return

    try:
        with ruv.unstashingStream(uv_server) as (vat, handler):
            uv_client = ruv.rffi.cast(ruv.stream_tp,
                                      ruv.alloc_tcp(vat.uv_loop))
            # Actually accept the connection.
            ruv.accept(uv_server, uv_client)
            # Incant the handler.
            from typhon.objects.collections.maps import EMPTY_MAP
            wrappedStream = ruv.wrapStream(uv_client, 2)
            vat.sendOnly(handler, RUN_2, [StreamSource(wrappedStream, vat),
                                          StreamSink(wrappedStream, vat)],
                         EMPTY_MAP)
    except:
        if not we_are_translated():
            raise


@autohelp
class TCP4ServerEndpoint(Object):
    """
    A TCPv4 server endpoint.
    """

    def __init__(self, port):
        self.port = port

    def toString(self):
        return u"<endpoint (IPv4, TCP): %d>" % (self.port,)

    @method("Any", "Any")
    def listen(self, handler):
        vat = currentVat.get()
        uv_server = ruv.alloc_tcp(vat.uv_loop)
        try:
            ruv.tcpBind(uv_server, "0.0.0.0", self.port)
        except ruv.UVError as uve:
            raise userError(u"listen/1: Couldn't listen: %s" %
                            uve.repr().decode("utf-8"))

        uv_stream = ruv.rffi.cast(ruv.stream_tp, uv_server)
        ruv.stashStream(uv_stream, (vat, handler))
        # XXX hardcoded backlog of 42
        ruv.listen(uv_stream, 42, connectionCB)

        return TCP4Server(uv_server)

    @method("Any", "Any")
    def listenStream(self, handler):
        vat = currentVat.get()
        uv_server = ruv.alloc_tcp(vat.uv_loop)
        try:
            ruv.tcpBind(uv_server, "0.0.0.0", self.port)
        except ruv.UVError as uve:
            raise userError(u"listenStream/1: Couldn't listen: %s" %
                            uve.repr().decode("utf-8"))

        uv_stream = ruv.rffi.cast(ruv.stream_tp, uv_server)
        ruv.stashStream(uv_stream, (vat, handler))
        # XXX hardcoded backlog of 42
        ruv.listen(uv_stream, 42, connectionStreamCB)

        return TCP4Server(uv_server)


@runnable(RUN_1)
def makeTCP4ServerEndpoint(port):
    """
    Make a TCPv4 server endpoint.
    """

    return TCP4ServerEndpoint(unwrapInt(port))
