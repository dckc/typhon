{stdenv, fetchzip, fetchFromGitHub, lib, libsodium, libuv, libffi, pkgconfig, pypy, pypyPackages, vmSrc, buildJIT}:

# $ nix-prefetch-hg https://bitbucket.org/pypy/pypy
let
  pypySrc = fetchzip {
    url = "https://bitbucket.org/pypy/pypy/downloads/pypy2-v6.0.0-src.tar.bz2";
    sha256 = "17wjrjd23k2m4cz2qvb0xxk1hwyk8xzbpa60l7r9y3lia7j1r8pm";
  };
  macropy = pypyPackages.buildPythonPackage rec {
    pname = "macropy";
    version = "1.0.4";
    name = "${pname}-${version}";
    src = fetchFromGitHub {
      owner = "lihaoyi";
      repo = "macropy";
      rev = "13993ccb08df21a0d63b091dbaae50b9dbb3fe3e";
      sha256 = "12496896c823h0849vnslbdgmn6z9mhfkckqa8sb8k9qqab7pyyl";
    };
  };
  optLevel = if buildJIT then "-Ojit" else "-O2";

in
stdenv.mkDerivation {
  name = "typhon-vm";

  src = vmSrc;

  buildInputs = [ pypy
                  pypyPackages.py pypyPackages.twisted pypyPackages.pytest
                  macropy pypySrc
                  pkgconfig libffi libuv libsodium ];
  propagatedBuildInputs = [ libffi libuv libsodium ];

  shellHook = ''
    export TYPHON_LIBRARY_PATH=${libuv.out}/lib:${libsodium.out}/lib
    export PYTHONPATH=$TMP/typhon:$PYTHONPATH
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

  buildPhase = ''
    source $stdenv/setup
    mkdir -p ./rpython/_cache
    cp -r ${pypySrc}/rpython .
    chmod -R u+w rpython/
    cp -r $src/main.py .
    # Run the tests.
    trial typhon
    # Do the actual translation.
    ${pypy}/bin/pypy -mrpython ${optLevel} main.py
    '';

  # We do still have the check phase, but we do the untranslated test before
  # we attempt translation.
  doCheck = false;
  checkPhase = "trial typhon";

  installPhase = ''
    mkdir $out
    cp mt-typhon $out/
    '';

  separateDebugInfo = true;
}
