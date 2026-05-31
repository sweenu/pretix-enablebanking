{
  description = "Automatically import bank transactions via Enable Banking into pretix";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      lib = nixpkgs.lib;
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: lib.genAttrs systems (system: f system);
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };

          pretixPython = pkgs.pretix.python;
          pyPkgs = pretixPython.pkgs;

          pretix-plugin-build = pyPkgs.callPackage ./plugin-build.nix { };
        in
        {
          default = pyPkgs.buildPythonPackage {
            pname = "pretix-enablebanking";
            version = "1.0.4";
            src = self;
            format = "pyproject";

            build-system = [
              pyPkgs.setuptools
              pretix-plugin-build
            ];

            dependencies = [
              pyPkgs.pretix
              pyPkgs.requests
            ];

            doCheck = false;

            pythonImportsCheck = [ "pretix_enablebanking" ];
          };
        }
      );
    };
}
