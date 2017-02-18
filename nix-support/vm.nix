{stdenv, fetchzip, lib, libsodium, libuv, libffi, pkgconfig, python27, python27Packages, vmSrc, buildJIT}:

# $ nix-prefetch-hg https://bitbucket.org/pypy/pypy
let
  pypySrc = fetchzip {
    url = "https://bitbucket.org/pypy/pypy/downloads/pypy2-v5.6.0-src.tar.bz2";
    sha256 = "1i4cjyl3wpb2dfg7dhi5vrv474skym90mn7flm696cqs4jl4s421";
  };
  optLevel = if buildJIT then "-Ojit" else "-O2";
in
stdenv.mkDerivation {
  name = "typhon-vm";
  buildInputs = [ python27
                  python27Packages.py python27Packages.pytest python27Packages.twisted
                  pypySrc
                  pkgconfig libffi libuv libsodium ];
  propagatedBuildInputs = [ libffi libuv libsodium ];
  shellHook = ''
    export TYPHON_LIBRARY_PATH=${libuv.out}/lib:${libsodium.out}/lib
    export PYTHONPATH=$TMP/typhon
    if [ -e $TMP/typhon ]; then
        rm -rf $TMP/typhon
    fi
    mkdir -p $TMP/typhon/rpython/_cache
    # Ridiculous, but necessary.
    cp -r ${pypySrc}/* $TMP/typhon
    chmod -R 755 $TMP/typhon
    typhon_cleanup () {
        rm -rf $TMP/typhon
    }
    trap typhon_cleanup EXIT
  '';
  # We do still have the check phase, but we do the untranslated test before
  # we attempt translation.
  doCheck = true;
  checkPhase = "trial typhon";
  buildPhase = ''
    source $stdenv/setup
    mkdir -p ./rpython/_cache
    cp -r ${pypySrc}/rpython .
    cp -r $src/main.py .
    # Run the tests.
    trial typhon
    # Do the actual translation.
    ${python27}/bin/python -mrpython ${optLevel} main.py
    '';
  installPhase = ''
    mkdir $out
    strip mt-typhon
    cp mt-typhon $out/
    '';
  src = vmSrc;
}
