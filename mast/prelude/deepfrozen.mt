def FinalSlot := _makeFinalSlot.asType()

object SubrangeGuard as DeepFrozenStamp:
    to get(superguard):
        return object SpecializedSubrangeGuard implements Selfless, TransparentStamp:
            to _uncall():
                return [SubrangeGuard, "get", [superguard]]
            to audit(audition):
                def expr := audition.getObjectExpr()
                def meth := escape e {
                    expr.getScript().getMethodNamed("coerce", e)
                } catch _ {
                    throw(audition.getFQName() + " has no coerce/2 method")
                }
                if ((def resultGuardExpr := meth.getResultGuard()) != null && resultGuardExpr.getNodeName() == "NounExpr"):
                    def resultGuardSlotGuard := audition.getGuard(resultGuardExpr.getName())
                    if (resultGuardSlotGuard =~ via (FinalSlot.extractGuard) resultGuard):
                        traceln("resultGuard is " + M.toString(resultGuard))
                        if (resultGuard == superguard || superguard._respondsTo("supersetOf", 1) && superguard.supersetOf(resultGuard)):
                            return true
                        throw(audition.getFQN() + " does not have a result guard implying " + M.toQuote(superguard) + ", but " + M.toQuote(resultGuard))
                    throw(audition.getFQN() + " does not have a determinable result guard, but <& " + resultGuardExpr.getName() + "> :" + M.toQuote(resultGuardSlotGuard))

            to coerce(specimen, ej):
                if (__auditedBy(SpecializedSubrangeGuard, specimen)):
                    return specimen
                else if (__auditedBy(SpecializedSubrangeGuard,
                                    def c := specimen._conformTo(SpecializedSubrangeGuard))):
                    return c
                else:
                    throw.eject(ej, ["Not approved as a subrange of " + M.toQuote(superguard)])

            to passes(specimen):
                escape notOk:
                    SpecializedSubrangeGuard.coerce(specimen, notOk)
                    return true
                return false

            to _printOn(out):
                out.quote(SubrangeGuard)
                out.print("[")
                out.quote(superguard)
                out.print("]")


def checkDeepFrozen(specimen, sofar, ej, root) as DeepFrozenStamp:
    def key := __equalizer.makeTraversalKey(specimen)
    if (sofar.contains(key)):
        # Oops, been here already.
        return
    def sofarther := sofar.with(key)
    if (__auditedBy(DeepFrozenStamp, specimen)):
        return
    else if (Ref.isBroken(specimen)):
        # Broken refs are DF if their problem is DF.
        checkDeepFrozen(Ref.optProblem(specimen), sofarther, ej, root)
        return
    else if (__auditedBy(Selfless, specimen) &&
             __auditedBy(TransparentStamp, specimen)):
        def [maker, verb, args :List] := specimen._uncall()
        checkDeepFrozen(maker, sofarther, ej, root)
        checkDeepFrozen(verb, sofarther, ej, root)
        for arg in args:
            checkDeepFrozen(arg, sofarther, ej, root)
    else:
        if (__equalizer.sameYet(specimen, root)):
            throw.eject(ej, M.toQuote(root) + " is not DeepFrozen")
        else:
            throw.eject(ej, M.toQuote(root) + " is not DeepFrozen because " +
                        M.toQuote(specimen) + " is not")


def auditDeepFrozen
def dataGuards := [Bool, Char, Double, Int, Str]
object DeepFrozen implements DeepFrozenStamp:

    to audit(audition):
        auditDeepFrozen(audition, throw)
        traceln("Success. " + audition.getFQN() + " is DF.")
        audition.ask(DeepFrozenStamp)
        return false

    to coerce(specimen, ej):
        return specimen

    to supersetOf(guard):
        if (guard == DeepFrozen):
            return true
        if (dataGuards.contains(guard)):
            return true
        # XXX orderedspace version of data guards
        if (guard =~ via (Same.extractValue) sameVal):
            escape notOk:
                return checkDeepFrozen(sameVal, [].asSet(), notOk, sameVal)
            return false
        traceln("guard is " + M.toQuote(guard))
        if (guard =~ via (FinalSlot.extractGuard) valGuard):
            return DeepFrozen.supersetOf(valGuard)
        if (guard =~ via (List.extractGuard) eltGuard):
            return DeepFrozen.supersetOf(eltGuard)
        if (SubrangeGuard[DeepFrozen].passes(guard)):
            return true
        return false

    to _printOn(out):
        out.print("DeepFrozen")

    #to optionally():
    #to eventually():

bind auditDeepFrozen(audition, fail) as DeepFrozenStamp:
    def objectExpr := audition.getObjectExpr()
    def patternSS := objectExpr.getName().getStaticScope()
    def closurePatts := (objectExpr.getScript().getStaticScope().namesUsed() -
                        patternSS.getDefNames())
    def methScope := objectExpr.getScript().getMethodNamed("run", throw).getStaticScope()

    for patt in closurePatts:
        def name := patt.getName()
        if (patternSS.getVarNames().contains(name)):
            throw.eject(fail, M.toQuote(name) + " in the definition of " +
                        audition.getFQN() + " is a variable pattern " +
                        "and therefore not DeepFrozen")
        else:
            def guard := audition.getGuard(name)
            traceln("Checking DFness of " + name + " :" + M.toString(guard))
            if (!DeepFrozen.supersetOf(guard)):
                throw.eject(fail,
                            M.toQuote(name) + " in the lexical scope of " +
                            audition.getFQN() + " does not have a guard " +
                            "implying DeepFrozen, but " + M.toQuote(guard))

[=> SubrangeGuard, => DeepFrozen]