{ system ? builtins.currentSystem, bakedVmSrc ? null, bakedMastSrc ? null }:
let
  nixpkgs = import <nixpkgs> { inherit system; };
  lib = nixpkgs.lib;
  libsodium0 = nixpkgs.libsodium.overrideDerivation (oldAttrs: {stripAllList = "lib";});
  vmSrc = if (bakedVmSrc != null) then bakedVmSrc else
    let loc = part: (toString ./..) + part;
     in builtins.filterSource (path: type:
      let p = toString path;
       in (lib.hasPrefix (loc "/typhon/") p &&
           (type == "directory" || lib.hasSuffix ".py" p)) ||
        p == loc "/typhon" ||
        p == loc "/main.py") ./..;
  mastSrc = if (bakedMastSrc != null) then bakedMastSrc else
    let loc = part: (toString ./..) + part;
       in builtins.filterSource (path: type:
        let p = toString path;
         in ((lib.hasPrefix (loc "/mast/") p &&
              (type == "directory" || lib.hasSuffix ".mt" p)) ||
             (lib.hasPrefix (loc "/boot/") p &&
              (type == "directory" || lib.hasSuffix ".ty" p || lib.hasSuffix ".mast" p)) ||
          p == loc "/mast" ||
          p == loc "/boot" ||
          p == loc "/Makefile" ||
          p == loc "/loader.mast" ||
          p == loc "/repl.mast")) ./..;
  typhon = with nixpkgs; rec {
    typhonVm = callPackage ./vm.nix { vmSrc = vmSrc;
                                      buildJIT = false;
                                      libsodium = libsodium0; };
    typhonVmCrashy = callPackage ./vm.nix { buildJIT = true; };
    mast = callPackage ./mast.nix { mastSrc = mastSrc;
                                    typhonVm = typhonVm; };
    typhonDumpMAST = callPackage ./dump.nix {};
    # XXX broken for unknown reasons
    # bench = callPackage ./bench.nix { typhonVm = typhonVm; mast = mast; }
    montePackage = callPackage ./montePackage.nix { typhonVm = typhonVm; mast = mast; };
    monteDockerPackage = lockSet: pkgs.dockerTools.buildImage {
              name = lockSet.mainPackage;
              tag = "latest";
              contents = typhon.montePackage lockSet;
              config = {
                Cmd = [ ("/bin/" + lockSet.packages.${lockSet.mainPackage}.entrypoint) ];
                WorkingDir = "";
              };
            };
    mt = callPackage ./mt.nix { typhonVm = typhonVm; mast = mast;
                                vmSrc = vmSrc; mastSrc = mastSrc; };
    mtLite = callPackage ./mt.nix { typhonVm = typhonVm; mast = mast;
                                    vmSrc = vmSrc; mastSrc = mastSrc; withBuild = false;};
    mtDocker = nixpkgs.dockerTools.buildImage {
        name = "monte";
        tag = "latest";
        contents = [mtLite typhonVm];
        config = {
            Cmd = [ "/bin/mt" "repl" ];
            WorkingDir = "/";
            };
        };
    };
in
  typhon