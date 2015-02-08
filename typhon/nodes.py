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

from collections import OrderedDict

from rpython.rlib.jit import assert_green, elidable, jit_debug, unroll_safe

from typhon.atoms import getAtom
from typhon.errors import Ejecting, LoadFailed, UserException
from typhon.objects.collections import ConstList, unwrapList
from typhon.objects.constants import NullObject, unwrapBool
from typhon.objects.data import CharObject, DoubleObject, IntObject, StrObject
from typhon.objects.ejectors import Ejector, throw
from typhon.objects.slots import FinalSlot, VarSlot
from typhon.objects.user import ScriptObject
from typhon.pretty import Buffer, LineWriter, OneLine
from typhon.smallcaps import Code, ops


class Compiler(object):

    def __init__(self):
        self.instructions = []

        self.atoms = OrderedDict()
        self.frame = OrderedDict()
        self.literals = OrderedDict()
        self.locals = OrderedDict()
        self.scripts = []

    def makeCode(self):
        atoms = self.atoms.keys()
        frame = self.frame.keys()
        literals = self.literals.keys()
        locals = self.locals.keys()

        code = Code(self.instructions, atoms, literals, frame, locals,
                    self.scripts)
        code.figureMaxDepth()
        return code

    def addInstruction(self, name, index):
        self.instructions.append((ops[name], index))

    def addAtom(self, verb, arity):
        atom = getAtom(verb, arity)
        if atom not in self.atoms:
            self.atoms[atom] = len(self.atoms)
        return self.atoms[atom]

    def addFrame(self, name):
        if name not in self.frame:
            self.frame[name] = len(self.frame)
        return self.frame[name]

    def addLiteral(self, literal):
        if literal not in self.literals:
            self.literals[literal] = len(self.literals)
        return self.literals[literal]

    def addLocal(self, name):
        if name not in self.locals:
            self.locals[name] = len(self.locals)
        return self.locals[name]

    def addScript(self, script):
        index = len(self.scripts)
        self.scripts.append(script)
        return index

    def literal(self, literal):
        index = self.addLiteral(literal)
        self.addInstruction("LITERAL", index)

    def call(self, verb, arity):
        atom = self.addAtom(verb, arity)
        self.addInstruction("CALL", atom)

    def markInstruction(self, name):
        index = len(self.instructions)
        self.addInstruction(name, 0)
        return index

    def patch(self, index):
        inst, _ = self.instructions[index]
        self.instructions[index] = inst, len(self.instructions)


def compile(node):
    compiler = Compiler()
    node.compile(compiler)
    return compiler.makeCode()


class InvalidAST(LoadFailed):
    """
    An AST was ill-formed.
    """


class Node(object):

    _immutable_ = True
    _attrs_ = "frameSize",

    # The frame size hack is as follows: Whatever the top node is, regardless
    # of type, it needs to be able to store frame size for evaluation since it
    # might not necessarily be a type of node which introduces a new scope.
    # The correct fix is to wrap all nodes in Hide before evaluating them.
    frameSize = -1

    def __repr__(self):
        b = Buffer()
        self.pretty(LineWriter(b))
        return b.get()

    @elidable
    def repr(self):
        return self.__repr__()

    def pretty(self, out):
        raise NotImplementedError

    def transform(self, f):
        """
        Apply the given transformation to all children of this node, and this
        node, bottom-up.
        """

        return f(self)

    def rewriteScope(self, scope):
        """
        Rewrite the scope definitions by altering names.
        """

        return self

    def usesName(self, name):
        """
        Whether a name is used within this node.
        """

        return False


class _Null(Node):

    _immutable_ = True
    _attrs_ = ()

    def pretty(self, out):
        out.write("null")

    def compile(self, compiler):
        compiler.literal(NullObject)


Null = _Null()


def nullToNone(node):
    return None if node is Null else node


class Int(Node):

    _immutable_ = True

    def __init__(self, i):
        self._i = i

    def pretty(self, out):
        out.write("%d" % self._i)

    def compile(self, compiler):
        index = compiler.literal(IntObject(self._i))


class Str(Node):

    _immutable_ = True

    def __init__(self, s):
        self._s = s

    def pretty(self, out):
        out.write('"%s"' % (self._s.encode("utf-8")))

    def compile(self, compiler):
        index = compiler.literal(StrObject(self._s))


def strToString(s):
    if not isinstance(s, Str):
        raise InvalidAST("not a Str!")
    return s._s


class Double(Node):

    _immutable_ = True

    def __init__(self, d):
        self._d = d

    def pretty(self, out):
        out.write("%f" % self._d)

    def compile(self, compiler):
        index = compiler.literal(DoubleObject(self._d))


class Char(Node):

    _immutable_ = True

    def __init__(self, c):
        self._c = c

    def pretty(self, out):
        out.write("'%s'" % (self._c.encode("utf-8")))

    def compile(self, compiler):
        index = compiler.literal(CharObject(self._c))


class Tuple(Node):

    _immutable_ = True

    _immutable_fields_ = "_t[*]",

    def __init__(self, t):
        self._t = t

    def pretty(self, out):
        out.write("[")
        l = self._t
        if l:
            head = l[0]
            tail = l[1:]
            head.pretty(out)
            for item in tail:
                out.write(", ")
                item.pretty(out)
        out.write("]")

    def transform(self, f):
        # I don't care if it's cheating. It's elegant and simple and pretty.
        return f(Tuple([node.transform(f) for node in self._t]))

    def rewriteScope(self, scope):
        return Tuple([node.rewriteScope(scope) for node in self._t])

    def usesName(self, name):
        uses = False
        for node in self._t:
            if node.usesName(name):
                uses = True
        return uses

    def compile(self, compiler):
        size = len(self._t)
        makeList = compiler.addFrame(u"__makeList")
        compiler.addInstruction("NOUN_FRAME", makeList)
        # [__makeList]
        for node in self._t:
            node.compile(compiler)
            # [__makeList x0 x1 ...]
        compiler.call(u"run", size)
        # [ConstList]


def tupleToList(t):
    if not isinstance(t, Tuple):
        raise InvalidAST("not a Tuple: " + t.__repr__())
    return t._t


class Assign(Node):

    _immutable_ = True

    frameIndex = -1

    def __init__(self, target, rvalue):
        self.target = target
        self.rvalue = rvalue

    @staticmethod
    def fromAST(target, rvalue):
        return Assign(nounToString(target), rvalue)

    def pretty(self, out):
        out.write(self.target.encode("utf-8"))
        out.write(" := ")
        self.rvalue.pretty(out)

    def transform(self, f):
        return f(Assign(self.target, self.rvalue.transform(f)))

    def rewriteScope(self, scope):
        # Read.
        newTarget = scope.getShadow(self.target)
        if newTarget is None:
            newTarget = self.target
        self = Assign(newTarget, self.rvalue.rewriteScope(scope))
        self.frameIndex = scope.getSeen(newTarget)
        return self

    def usesName(self, name):
        return self.rvalue.usesName(name)

    def compile(self, compiler):
        self.rvalue.compile(compiler)
        # [rvalue]
        compiler.addInstruction("DUP", 0)
        # [rvalue rvalue]
        # It's unknown yet whether the assignment is to a local slot or an
        # (outer) frame slot. Check to see whether the name is already known
        # to be local; if not, then it must be in the outer frame.
        if self.target in compiler.locals:
            index = compiler.locals[self.target]
            compiler.addInstruction("ASSIGN_LOCAL", index)
            # [rvalue]
        else:
            index = compiler.addFrame(self.target)
            compiler.addInstruction("ASSIGN_FRAME", index)
            # [rvalue]


class Binding(Node):

    _immutable_ = True

    frameIndex = -1

    def __init__(self, name):
        self.name = name

    @staticmethod
    def fromAST(noun):
        return Binding(nounToString(noun))

    def pretty(self, out):
        out.write("&&")
        out.write(self.name.encode("utf-8"))

    def transform(self, f):
        return f(self)

    def rewriteScope(self, scope):
        # Read.
        newName = scope.getShadow(self.name)
        if newName is not None:
            self = Binding(newName)
        self.frameIndex = scope.getSeen(self.name)
        return self

    def compile(self, compiler):
        if self.name in compiler.locals:
            index = compiler.addLocal(self.name)
            compiler.addInstruction("BINDING_LOCAL", index)
            # [binding]
        else:
            index = compiler.addFrame(self.name)
            compiler.addInstruction("BINDING_FRAME", index)
            # [binding]


class Call(Node):

    _immutable_ = True

    def __init__(self, target, verb, args):
        self._target = target
        self._verb = verb
        self._args = args

    def pretty(self, out):
        self._target.pretty(out)
        out.write(".")
        self._verb.pretty(out)
        out.write("(")
        self._args.pretty(out)
        out.write(")")

    def transform(self, f):
        return f(Call(self._target.transform(f), self._verb.transform(f),
            self._args.transform(f)))

    def rewriteScope(self, scope):
        return Call(self._target.rewriteScope(scope),
                    self._verb.rewriteScope(scope),
                    self._args.rewriteScope(scope))

    def usesName(self, name):
        rv = self._target.usesName(name) or self._verb.usesName(name)
        return rv or self._args.usesName(name)

    def compile(self, compiler):
        self._target.compile(compiler)
        # [target]
        verb = strToString(self._verb)
        args = tupleToList(self._args)
        arity = len(args)
        for node in args:
            node.compile(compiler)
            # [target x0 x1 ...]
        compiler.call(verb, arity)
        # [retval]

class Def(Node):

    _immutable_ = True

    def __init__(self, pattern, ejector, value):
        self._p = pattern
        self._e = ejector
        self._v = value

    @staticmethod
    def fromAST(pattern, ejector, value):
        if pattern is None:
            raise InvalidAST("Def pattern cannot be None")

        return Def(pattern, nullToNone(ejector),
                value if value is not None else Null)

    def pretty(self, out):
        out.write("def ")
        self._p.pretty(out)
        if self._e is not None:
            out.write(" exit ")
            self._e.pretty(out)
        out.write(" := ")
        self._v.pretty(out)
        out.writeLine("")

    def transform(self, f):
        return f(Def(self._p, self._e, self._v.transform(f)))

    def rewriteScope(self, scope):
        # Delegate to patterns.
        p = self._p.rewriteScope(scope)
        if self._e is None:
            e = None
        else:
            e = self._e.rewriteScope(scope)
        return Def(p, e, self._v.rewriteScope(scope))

    def usesName(self, name):
        rv = self._v.usesName(name)
        if self._e is not None:
            rv = rv or self._e.usesName(name)
        return rv

    def compile(self, compiler):
        self._v.compile(compiler)
        # [value]
        compiler.addInstruction("DUP", 0)
        # [value value]
        if self._e is None:
            compiler.literal(NullObject)
            # [value value null]
        else:
            self._e.compile(compiler)
            # [value value ej]
        self._p.compile(compiler)
        # [value]


class Escape(Node):

    _immutable_ = True

    frameSize = -1
    catchFrameSize = -1

    def __init__(self, pattern, node, catchPattern, catchNode):
        self._pattern = pattern
        self._node = node
        self._catchPattern = catchPattern
        self._catchNode = nullToNone(catchNode)

    def pretty(self, out):
        out.write("escape ")
        self._pattern.pretty(out)
        out.writeLine(":")
        self._node.pretty(out.indent())
        if self._catchPattern is not None and self._catchNode is not None:
            out.write("catch ")
            self._catchPattern.pretty(out)
            out.writeLine(":")
            self._catchNode.pretty(out.indent())

    def transform(self, f):
        # We have to write some extra code here since catchNode could be None.
        if self._catchNode is None:
            catchNode = None
        else:
            catchNode = self._catchNode.transform(f)

        return f(Escape(self._pattern, self._node.transform(f),
            self._catchPattern, catchNode))

    def rewriteScope(self, scope):
        with scope:
            p = self._pattern.rewriteScope(scope)
            n = self._node.rewriteScope(scope)
            frameSize = scope.size()

        with scope:
            if self._catchPattern is None:
                cp = None
            else:
                cp = self._catchPattern.rewriteScope(scope)
            if self._catchNode is None:
                cn = None
            else:
                cn = self._catchNode.rewriteScope(scope)
            catchFrameSize = scope.size()

        rv = Escape(p, n, cp, cn)
        rv.frameSize = frameSize
        rv.catchFrameSize = catchFrameSize
        return rv

    def usesName(self, name):
        rv = self._node.usesName(name)
        if self._catchNode is not None:
            rv = rv or self._catchNode.usesName(name)
        return rv

    def compile(self, compiler):
        ejector = compiler.markInstruction("EJECTOR")
        # [ej]
        compiler.literal(NullObject)
        # [ej null]
        self._pattern.compile(compiler)
        # []
        self._node.compile(compiler)
        # [retval]
        if self._catchNode is not None:
            jump = compiler.markInstruction("JUMP")
            compiler.patch(ejector)
            compiler.literal(NullObject)
            # [retval null]
            self._catchPattern.compile(compiler)
            # []
            self._catchNode.compile(compiler)
            # [retval]
            compiler.patch(jump)
        else:
            compiler.patch(ejector)


class Finally(Node):

    _immutable_ = True

    frameSize = -1
    finallyFrameSize = -1

    def __init__(self, block, atLast):
        self._block = block
        self._atLast = atLast

    def pretty(self, out):
        out.writeLine("try:")
        self._block.pretty(out.indent())
        out.writeLine("")
        out.writeLine("finally:")
        self._atLast.pretty(out.indent())

    def transform(self, f):
        return f(Finally(self._block.transform(f), self._atLast.transform(f)))

    def rewriteScope(self, scope):
        with scope:
            block = self._block.rewriteScope(scope)
            frameSize = scope.size()

        with scope:
            atLast = self._atLast.rewriteScope(scope)
            finallyFrameSize = scope.size()

        rv = Finally(block, atLast)
        rv.frameSize = frameSize
        rv.finallyFrameSize = finallyFrameSize
        return rv

    def usesName(self, name):
        return self._block.usesName(name) or self._atLast.usesName(name)

    def compile(self, compiler):
        unwind = compiler.markInstruction("UNWIND")
        self._block.compile(compiler)
        handler = compiler.markInstruction("END_HANDLER")
        compiler.patch(unwind)
        self._atLast.compile(compiler)
        compiler.addInstruction("POP", 0)
        dropper = compiler.markInstruction("END_HANDLER")
        compiler.patch(handler)
        compiler.patch(dropper)


class Hide(Node):

    _immutable_ = True

    frameSize = -1

    def __init__(self, inner):
        self._inner = inner

    def pretty(self, out):
        out.writeLine("hide:")
        self._inner.pretty(out.indent())

    def transform(self, f):
        return f(Hide(self._inner.transform(f)))

    def rewriteScope(self, scope):
        with scope:
            rv = Hide(self._inner.rewriteScope(scope))
            frameSize = scope.size()

        rv.frameSize = frameSize
        return rv

    def usesName(self, name):
        # XXX not technically correct due to Hide intentionally altering
        # scope resolution.
        return self._inner.usesName(name)

    def compile(self, compiler):
        self._inner.compile(compiler)


class If(Node):

    _immutable_ = True

    frameSize = -1

    def __init__(self, test, then, otherwise):
        self._test = test
        self._then = then
        self._otherwise = otherwise

    def pretty(self, out):
        out.write("if (")
        self._test.pretty(out)
        out.writeLine("):")
        self._then.pretty(out.indent())
        out.writeLine("")
        out.writeLine("else:")
        self._otherwise.pretty(out.indent())

    def transform(self, f):
        return f(If(self._test.transform(f), self._then.transform(f),
            self._otherwise.transform(f)))

    def rewriteScope(self, scope):
        with scope:
            rv = If(self._test.rewriteScope(scope),
                    self._then.rewriteScope(scope),
                    self._otherwise.rewriteScope(scope))
            frameSize = scope.size()

        rv.frameSize = frameSize
        return rv

    def usesName(self, name):
        rv = self._test.usesName(name) or self._then.usesName(name)
        return rv or self._otherwise.usesName(name)

    def compile(self, compiler):
        # BRANCH otherwise
        # ...
        # JUMP end
        # otherwise: ...
        # end: ...
        self._test.compile(compiler)
        # [condition]
        branch = compiler.markInstruction("BRANCH")
        self._then.compile(compiler)
        jump = compiler.markInstruction("JUMP")
        compiler.patch(branch)
        self._otherwise.compile(compiler)
        compiler.patch(jump)


class Matcher(Node):

    _immutable_ = True

    frameSize = -1

    def __init__(self, pattern, block):
        if pattern is None:
            raise InvalidAST("Matcher pattern cannot be None")

        self._pattern = pattern
        self._block = block

    def pretty(self, out):
        out.write("match ")
        self._pattern.pretty(out)
        out.writeLine(":")
        self._block.pretty(out.indent())
        out.writeLine("")

    def transform(self, f):
        return f(Matcher(self._pattern, self._block.transform(f)))

    def rewriteScope(self, scope):
        with scope:
            rv = Matcher(self._pattern.rewriteScope(scope),
                         self._block.rewriteScope(scope))
            frameSize = scope.size()

        rv.frameSize = frameSize
        return rv


class Method(Node):

    _immutable_ = True

    _immutable_fields_ = "_ps[*]",

    frameSize = -1

    def __init__(self, doc, verb, params, guard, block):
        self._d = doc
        self._verb = verb
        self._ps = params
        self._g = guard
        self._b = block

    @staticmethod
    def fromAST(doc, verb, params, guard, block):
        for param in params:
            if param is None:
                raise InvalidAST("Parameter patterns cannot be None")

        return Method(doc, strToString(verb), params, guard, block)

    def pretty(self, out):
        out.write("method ")
        out.write(self._verb.encode("utf-8"))
        out.write("(")
        l = self._ps
        if l:
            head = l[0]
            tail = l[1:]
            head.pretty(out)
            for item in tail:
                out.write(", ")
                item.pretty(out)
        out.write(") :")
        self._g.pretty(out)
        out.writeLine(":")
        self._b.pretty(out.indent())
        out.writeLine("")

    def transform(self, f):
        return f(Method(self._d, self._verb, self._ps, self._g,
            self._b.transform(f)))

    def rewriteScope(self, scope):
        with scope:
            ps = [p.rewriteScope(scope) for p in self._ps]
            rv = Method(self._d, self._verb, ps,
                        self._g.rewriteScope(scope),
                        self._b.rewriteScope(scope))
            frameSize = scope.size()

        rv.frameSize = frameSize
        return rv

    def usesName(self, name):
        return self._b.usesName(name)


class Noun(Node):

    _immutable_ = True

    frameIndex = -1

    def __init__(self, noun):
        self.name = noun

    @staticmethod
    def fromAST(noun):
        return Noun(strToString(noun))

    def pretty(self, out):
        out.write(self.name.encode("utf-8"))

    def rewriteScope(self, scope):
        # Read.
        newName = scope.getShadow(self.name)
        if newName is not None:
            self = Noun(newName)
        self.frameIndex = scope.getSeen(self.name)
        return self

    def usesName(self, name):
        return self.name == name

    def compile(self, compiler):
        if self.name in compiler.locals:
            index = compiler.addLocal(self.name)
            compiler.addInstruction("NOUN_LOCAL", index)
        else:
            index = compiler.addFrame(self.name)
            compiler.addInstruction("NOUN_FRAME", index)


def nounToString(n):
    if not isinstance(n, Noun):
        raise InvalidAST("Not a Noun")
    return n.name


class Obj(Node):

    _immutable_ = True

    _immutable_fields_ = "_implements[*]",

    def __init__(self, doc, name, objectAs, implements, script):
        self._d = doc
        self._n = name
        self._as = objectAs
        self._implements = implements
        self._script = script

        # Create a cached code object for this object.
        self.codeScript = CodeScript(formatName(name))
        self.codeScript.addScript(self._script)

    @staticmethod
    def fromAST(doc, name, auditors, script):
        if name is None:
            raise InvalidAST("Object pattern cannot be None")

        auditors = tupleToList(auditors)
        if not isinstance(script, Script):
            raise InvalidAST("Object's script isn't a Script")

        return Obj(doc, name, nullToNone(auditors[0]), auditors[1:], script)

    def pretty(self, out):
        out.write("object ")
        self._n.pretty(out)
        # XXX doc, as, implements
        out.writeLine(":")
        self._script.pretty(out.indent())

    def transform(self, f):
        return f(Obj(self._d, self._n, self._as, self._implements,
            self._script.transform(f)))

    def rewriteScope(self, scope):
        # XXX as, implements
        return Obj(self._d, self._n.rewriteScope(scope), self._as,
                   self._implements, self._script.rewriteScope(scope))

    def usesName(self, name):
        return self._script.usesName(name)

    def compile(self, compiler):
        for name in self.codeScript.closureNames:
            if name == self.codeScript.displayName:
                # Put in a null and patch it later via UserObject.patchSelf().
                compiler.literal(NullObject)
            elif name in compiler.locals:
                index = compiler.addLocal(name)
                compiler.addInstruction("BINDING_LOCAL", index)
            else:
                index = compiler.addFrame(name)
                compiler.addInstruction("BINDING_FRAME", index)
        index = compiler.addScript(self.codeScript)
        compiler.addInstruction("BINDOBJECT", index)
        compiler.addInstruction("DUP", 0)
        compiler.literal(NullObject)
        self._n.compile(compiler)


class CodeScript(object):

    def __init__(self, displayName):
        self.displayName = displayName

        self.methods = {}
        self.matchers = []
        self.closureNames = {}

    def makeObject(self, closure):
        return ScriptObject(self, closure, self.displayName)

    def addScript(self, script):
        assert isinstance(script, Script)
        for method in script._methods:
            assert isinstance(method, Method)
            self.addMethod(method)
        for matcher in script._matchers:
            self.addMatcher(matcher)

    def addMethod(self, method):
        verb = method._verb
        arity = len(method._ps)
        compiler = Compiler()
        for param in method._ps:
            param.compile(compiler)
        method._b.compile(compiler)
        # XXX guard

        code = compiler.makeCode()
        atom = getAtom(verb, arity)
        self.methods[atom] = code

        for name in code.frame:
            self.closureNames[name] = None

    def addMatcher(self, matcher):
        # XXX
        pass


class Script(Node):

    _immutable_ = True

    _immutable_fields_ = "_methods[*]", "_matchers[*]"

    def __init__(self, extends, methods, matchers):
        self._extends = extends
        self._methods = methods
        self._matchers = matchers

    @staticmethod
    def fromAST(extends, methods, matchers):
        extends = nullToNone(extends)
        methods = tupleToList(methods)
        for method in methods:
            if not isinstance(method, Method):
                raise InvalidAST("Script method isn't a Method")
        if matchers is Null:
            matchers = []
        else:
            matchers = tupleToList(matchers)
        for matcher in matchers:
            if not isinstance(matcher, Matcher):
                raise InvalidAST("Script matcher isn't a Matcher")

        return Script(extends, methods, matchers)

    def pretty(self, out):
        for method in self._methods:
            method.pretty(out)
        for matcher in self._matchers:
            matcher.pretty(out)

    def transform(self, f):
        methods = [method.transform(f) for method in self._methods]
        return f(Script(self._extends, methods, self._matchers))

    def rewriteScope(self, scope):
        methods = [m.rewriteScope(scope) for m in self._methods]
        matchers = [m.rewriteScope(scope) for m in self._matchers]
        return Script(self._extends, methods, matchers)

    def usesName(self, name):
        for method in self._methods:
            if method.usesName(name):
                return True
        for matcher in self._matchers:
            if matcher.usesName(name):
                return True
        return False


class Sequence(Node):

    _immutable_ = True

    _immutable_fields_ = "_l[*]",

    def __init__(self, l):
        self._l = l

    @staticmethod
    def fromAST(t):
        return Sequence(tupleToList(t))

    def pretty(self, out):
        for item in self._l:
            item.pretty(out)
            out.writeLine("")

    def transform(self, f):
        return f(Sequence([node.transform(f) for node in self._l]))

    def rewriteScope(self, scope):
        return Sequence([n.rewriteScope(scope) for n in self._l])

    def usesName(self, name):
        for node in self._l:
            if node.usesName(name):
                return True
        return False

    def compile(self, compiler):
        for node in self._l[:-1]:
            node.compile(compiler)
            compiler.addInstruction("POP", 0)
        self._l[-1].compile(compiler)


class Try(Node):

    _immutable_ = True

    frameSize = -1
    catchFrameSize = -1

    def __init__(self, first, pattern, then):
        self._first = first
        self._pattern = pattern
        self._then = then

    def pretty(self, out):
        out.writeLine("try:")
        self._first.pretty(out.indent())
        out.writeLine("")
        out.write("catch ")
        self._pattern.pretty(out)
        out.writeLine(":")
        self._then.pretty(out.indent())

    def transform(self, f):
        return f(Try(self._first.transform(f), self._pattern,
            self._then.transform(f)))

    def rewriteScope(self, scope):
        with scope:
            first = self._first.rewriteScope(scope)
            frameSize = scope.size()

        with scope:
            rv = Try(first, self._pattern.rewriteScope(scope),
                     self._then.rewriteScope(scope))
            catchFrameSize = scope.size()

        rv.frameSize = frameSize
        rv.catchFrameSize = catchFrameSize
        return rv

    def usesName(self, name):
        return self._first.usesName(name) or self._then.usesName(name)

    def compile(self, compiler):
        index = compiler.markInstruction("TRY")
        self._first.compile(compiler)
        end = compiler.markInstruction("END_HANDLER")
        compiler.patch(index)
        self._pattern.compile(compiler)
        self._then.compile(compiler)
        compiler.patch(end)


class Pattern(object):

    _immutable_ = True

    def __repr__(self):
        b = Buffer()
        self.pretty(LineWriter(b))
        return b.get()

    def repr(self):
        return self.__repr__()


class BindingPattern(Pattern):

    _immutable_ = True

    frameIndex = -1

    def __init__(self, noun):
        self._noun = nounToString(noun)

    def pretty(self, out):
        out.write("&&")
        out.write(self._noun.encode("utf-8"))

    def unify(self, specimen, ejector, env):
        env.createBinding(self.frameIndex, specimen)

    def rewriteScope(self, scope):
        # Write.
        if scope.getSeen(self._noun) != -1:
            # Shadow.
            shadowed = scope.shadowName(self._noun)
            self = BindingPattern(Noun(shadowed))
        self.frameIndex = scope.putSeen(self._noun)
        return self

    def compile(self, compiler):
        index = compiler.addLocal(self._noun)
        compiler.addInstruction("POP", 0)
        compiler.addInstruction("BIND", index)


class FinalPattern(Pattern):

    _immutable_ = True

    frameIndex = -1

    def __init__(self, noun, guard):
        self._n = nounToString(noun)
        self._g = nullToNone(guard)

    def pretty(self, out):
        out.write(self._n.encode("utf-8"))
        if self._g is not None:
            out.write(" :")
            self._g.pretty(out)

    def unify(self, specimen, ejector, env):
        if self._g is None:
            rv = specimen
        else:
            # Get the guard.
            guard = evaluate(self._g, env)

            # Since this is a final assignment, we can run the specimen through
            # the guard once and for all, right now.
            rv = guard.call(u"coerce", [specimen, ejector])

        slot = FinalSlot(rv)
        env.createSlot(self.frameIndex, slot)

    def rewriteScope(self, scope):
        if self._g is None:
            g = None
        else:
            g = self._g.rewriteScope(scope)

        # Write.
        if scope.getSeen(self._n) != -1:
            # Shadow.
            shadowed = scope.shadowName(self._n)
            self = FinalPattern(Noun(shadowed), g)
        self.frameIndex = scope.putSeen(self._n)
        return self

    def compile(self, compiler):
        # [specimen ej]
        if self._g is None:
            compiler.addInstruction("POP", 0)
            # [specimen]
        else:
            self._g.compile(compiler)
            # [specimen ej guard]
            compiler.addInstruction("ROT", 0)
            compiler.addInstruction("ROT", 0)
            # [guard specimen ej]
            compiler.call(u"coerce", 2)
            # [specimen]
        index = compiler.addFrame(u"_makeFinalSlot")
        compiler.addInstruction("NOUN_FRAME", index)
        compiler.addInstruction("SWAP", 0)
        # [_makeFinalSlot specimen]
        compiler.call(u"run", 1)
        index = compiler.addLocal(self._n)
        compiler.addInstruction("BINDSLOT", index)


class IgnorePattern(Pattern):

    _immutable_ = True

    def __init__(self, guard):
        self._g = nullToNone(guard)

    def pretty(self, out):
        out.write("_")
        if self._g is not None:
            out.write(" :")
            self._g.pretty(out)

    def unify(self, specimen, ejector, env):
        # We don't have to do anything, unless somebody put a guard on an
        # ignore pattern. Who would do such a thing?
        if self._g is not None:
            guard = evaluate(self._g, env)
            guard.call(u"coerce", [specimen, ejector])

    def rewriteScope(self, scope):
        if self._g is None:
            return self
        return IgnorePattern(self._g.rewriteScope(scope))

    def compile(self, compiler):
        # [specimen ej]
        if self._g is None:
            compiler.addInstruction("POP", 0)
            compiler.addInstruction("POP", 0)
        else:
            self._g.compile(compiler)
            # [specimen ej guard]
            compiler.addInstruction("ROT", 0)
            compiler.addInstruction("ROT", 0)
            # [guard specimen ej]
            compiler.call(u"coerce", 2)


class ListPattern(Pattern):

    _immutable_ = True

    _immutable_fields_ = "_ps[*]",

    def __init__(self, patterns, tail):
        for p in patterns:
            if p is None:
                raise InvalidAST("List subpattern cannot be None")

        self._ps = patterns
        self._t = tail

    def pretty(self, out):
        out.write("[")
        for pattern in self._ps:
            pattern.pretty(out)
            out.write(", ")
        out.write("]")
        if self._t is not None:
            out.write(" | ")
            self._t.pretty(out)

    @unroll_safe
    def unify(self, specimen, ejector, env):
        patterns = self._ps
        tail = self._t

        # Can't unify lists and non-lists.
        if not isinstance(specimen, ConstList):
            throw(ejector, StrObject(u"Can't unify lists and non-lists"))

        items = unwrapList(specimen)

        # If we have no tail, then unification isn't going to work if the
        # lists are of differing lengths.
        if tail is None and len(patterns) != len(items):
            throw(ejector, StrObject(u"Lists are different lengths"))

        # Even if there's a tail, there must be at least as many elements in
        # the pattern list as there are in the specimen list.
        elif len(patterns) > len(items):
            throw(ejector, StrObject(u"List is too short"))

        # Actually unify. Because of the above checks, this shouldn't run
        # ragged.
        for i, pattern in enumerate(patterns):
            pattern.unify(items[i], ejector, env)

        # And unify the tail as well.
        if tail is not None:
            remainder = ConstList(items[len(patterns):])
            tail.unify(remainder, ejector, env)

    def rewriteScope(self, scope):
        ps = [p.rewriteScope(scope) for p in self._ps]
        if self._t is None:
            t = None
        else:
            t = self._t.rewriteScope(scope)
        return ListPattern(ps, t)

    def compile(self, compiler):
        # XXX tail is assumed to be null/none
        # [specimen ej]
        compiler.addInstruction("LIST_PATT", len(self._ps))
        for patt in self._ps:
            # [specimen ej]
            patt.compile(compiler)


class VarPattern(Pattern):

    _immutable_ = True

    frameIndex = -1

    def __init__(self, noun, guard):
        self._n = nounToString(noun)
        self._g = nullToNone(guard)

    def pretty(self, out):
        out.write("var ")
        out.write(self._n.encode("utf-8"))
        if self._g is not None:
            out.write(" :")
            self._g.pretty(out)

    def unify(self, specimen, ejector, env):
        if self._g is None:
            rv = VarSlot(specimen)
        else:
            # Get the guard.
            guard = evaluate(self._g, env)

            # Generate a slot.
            rv = guard.call(u"makeSlot", [specimen])

        # Add the slot to the environment.
        env.createSlot(self.frameIndex, rv)

    def rewriteScope(self, scope):
        if self._g is None:
            g = None
        else:
            g = self._g.rewriteScope(scope)

        # Write.
        if scope.getSeen(self._n) != -1:
            # Shadow.
            shadowed = scope.shadowName(self._n)
            self = VarPattern(Noun(shadowed), g)
        self.frameIndex = scope.putSeen(self._n)
        return self

    def compile(self, compiler):
        # [specimen ej]
        if self._g is None:
            compiler.addInstruction("POP", 0)
        else:
            self._g.compile(compiler)
            # [specimen ej guard]
            compiler.addInstruction("ROT", 0)
            compiler.addInstruction("ROT", 0)
            # [guard specimen ej]
            compiler.call(u"coerce", 2)
        index = compiler.addFrame(u"_makeVarSlot")
        compiler.addInstruction("NOUN_FRAME", index)
        compiler.addInstruction("SWAP", 0)
        # [_makeVarSlot specimen]
        compiler.call(u"run", 1)
        index = compiler.addLocal(self._n)
        compiler.addInstruction("BINDSLOT", index)


class ViaPattern(Pattern):

    _immutable_ = True

    def __init__(self, expr, pattern):
        self._expr = expr
        if pattern is None:
            raise InvalidAST("Inner pattern of via cannot be None")
        self._pattern = pattern

    def pretty(self, out):
        out.write("via (")
        self._expr.pretty(out)
        out.write(") ")
        self._pattern.pretty(out)

    def unify(self, specimen, ejector, env):
        # This one always bamboozles me, so I'll spell out what it's doing.
        # The via pattern takes an expression and another pattern, and passes
        # the specimen into the expression along with an ejector. The
        # expression can reject the specimen by escaping, or it can transform
        # the specimen and return a new specimen which is then applied to the
        # inner pattern.
        examiner = evaluate(self._expr, env)
        self._pattern.unify(examiner.call(u"run", [specimen, ejector]),
                ejector, env)

    def rewriteScope(self, scope):
        return ViaPattern(self._expr.rewriteScope(scope),
                          self._pattern.rewriteScope(scope))

    def compile(self, compiler):
        # [specimen ej]
        compiler.addInstruction("DUP", 0)
        # [specimen ej ej]
        compiler.addInstruction("ROT", 0)
        # [ej ej specimen]
        compiler.addInstruction("SWAP", 0)
        # [ej specimen ej]
        self._expr.compile(compiler)
        # [ej specimen ej examiner]
        compiler.addInstruction("ROT", 0)
        compiler.addInstruction("ROT", 0)
        # [ej examiner specimen ej]
        compiler.call(u"run", 2)
        # [ej specimen]
        compiler.addInstruction("SWAP", 0)
        # [specimen ej]
        self._pattern.compile(compiler)


def formatName(p):
    if isinstance(p, FinalPattern):
        return p._n
    return u"_"
