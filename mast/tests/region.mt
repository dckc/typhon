import "unittest" =~ [=> unittest]

def testIterable(assert):
    def intspace := _makeOrderedSpace(Int, "Int")
    def reg := (intspace >= 0) & (intspace < 5)
    assert.equal(_makeList.fromIterable(reg), [0, 1, 2, 3, 4])

def testContainment(assert):
    def intspace := _makeOrderedSpace(Int, "Int")
    def reg := (intspace >= 0) & (intspace < 5)
    assert.equal(reg(3), true)
    assert.equal(reg(5), false)
    assert.throws(fn {reg(1.0)})

def testGuard(assert):
    def intspace := _makeOrderedSpace(Int, "Int")
    def reg := (intspace >= 0) & (intspace < 5)
    assert.equal(def x :reg := 3, 3)
    assert.ejects(fn ej {def x :reg exit ej := 7})

def testDeepFrozen(assert):
    def intspace := _makeOrderedSpace(Int, "Int")
    def reg := (intspace >= 0) & (intspace < 5)
    def x :reg := 2
    object y implements DeepFrozen:
        to add(a):
            return a + x
    assert.equal(y =~ _ :DeepFrozen, true)

unittest([testIterable, testContainment, testGuard, testDeepFrozen])
