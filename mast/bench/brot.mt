import "bench" =~ [=> bench]
import "lib/codec/utf8" =~ [=> UTF8 :DeepFrozen]
import "lib/complex" =~ [=> makeComplex :DeepFrozen]
import "lib/ansiColor" =~ [=> ramp :DeepFrozen]
import "lib/streams" =~ [=> alterSink :DeepFrozen]
exports (main)


def ITERATIONS :Int := 170


def brotCount(a) :Int as DeepFrozen:
    var rv := makeComplex(0.0, 0.0)
    var i := ITERATIONS
    while (i > 0 && rv.abs() <= 2):
        rv := makeComplex(rv.real().abs(), rv.imag().abs())
        rv := rv * rv + a
        i -= 1
    # traceln(["Iterations", i, "Seed", a.real(), a.imag()])
    return i


def getScaled(l, count :Int) as DeepFrozen:
    def range := l.size()
    def index := (count * range // ITERATIONS).min(range - 1)
    return l[index]


def chars :Str := "@#&%!*+-."
# def colors :List[Str] := ["37", "32", "33", "31", "36", "35", "34"]
def ramp80 :List[Str] := [for i in (ramp(80)) `38;5;$i`].reverse()


def format(count :Int) :Str as DeepFrozen:
    def c := getScaled(chars, count)
    # def color := getScaled(colors, count)
    def color := getScaled(ramp80, count)
    return `$\u001b[${color}m$c`


def doStep(start :Double, step :Double, iterations :Int) :List[Double] as DeepFrozen:
    return [for i in (0..!iterations) start + i * step]


def fullBrot(write, yStart :Double, yStep :Double, xStart :Double,
             xStep :Double) :Void as DeepFrozen:
    for y in (doStep(yStart, yStep, 40)):
        for x in (doStep(xStart, xStep, 80)):
            def count := brotCount(makeComplex(x, y))
            write(format(count))
        write("\n")
    write("\u001b[0m\n")


def brotAt(write, xCenter :Double, yCenter :Double, xScale :Double, 
           yScale :Double) :Void as DeepFrozen:
    def xStart := xCenter - xScale * 40
    def yStart := yCenter - yScale * 20
    fullBrot(write, yStart, yScale, xStart, xScale)


def voidWrite(_) :Void:
    null

bench(fn {brotAt(voidWrite, -0.25, -0.4, 1 / 32.0, 1 / 20.0)},
      "Burning ship (large)")
bench(fn {brotAt(voidWrite, -1.7529296875, -0.025, 1 / 1024.0, 1 / 640.0)},
      "Burning ship (small)")

def main(_argv, => stdio) :Int as DeepFrozen:
    def stdout := alterSink.encodeWith(UTF8, stdio.stdout())

    # And you thought Pokémon Snap was hard. ~ C.
    brotAt(stdout, -0.25, -0.4, 1 / 32.0, 1 / 20.0)
    brotAt(stdout, -1.7529296875, -0.025, 1 / 1024.0, 1 / 640.0)

    return 0
