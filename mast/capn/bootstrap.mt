import "lib/capn" =~ [=> text :DeepFrozen]
exports (builder)

def Brand(_root) as DeepFrozen:
    return object brand {}

def Type(root) as DeepFrozen:
    def which := root.getWord(0) & 0xff
    return object type:
        to _which():
            return which
        to typeId():
            return root.getWord(1)
        to elementType():
            return Type(root.getPointer(0))
        to brand():
            return Brand(root.getPointer(0))

def Field(root) as DeepFrozen:
    def which := root.getWord(1) & 0xff
    return object field:
        to _which():
            return which
        to discriminantValue():
            return root.getWord(0) >> 16 & 0xff
        to name():
            return text(root.getPointer(0))
        to slot():
            return object slot:
                to offset():
                    return root.getWord(0) >> 32
                to type():
                    return Type(root.getPointer(2))
        to group():
            return def group.typeId():
                return root.getWord(2)

def Node(root) as DeepFrozen:
    def which := root.getWord(1) >> 32 & 0xff
    return object node:
        to _which():
            return which
        to id():
            return root.getWord(0)
        to displayNamePrefixLength():
            return root.getWord(1) & 0xffff
        to displayName():
            return text(root.getPointer(0))
        to fields():
            return [for r in (root.getPointer(3)) Field(r)]
        to struct():
            return object struct:
                to discriminantCount():
                    return root.getWord(3) >> 48 & 0xffff
                to discriminantOffset():
                    return root.getWord(4) & 0xffffffff

object builder as DeepFrozen:
    to CodeGeneratorRequest(root :DeepFrozen):
        return object cgr:
            to nodes():
                return [for r in (root.getPointer(0)) Node(r)]
            to requestedFiles():
                return root.getPointer(1)

    to derp():
        null
