with import <nixpkgs> {};

let 
  python = python3;
  audiotsm = python.pkgs.buildPythonPackage {
      name = "audiotsm-0.1.2";
      src = pkgs.fetchurl { url = "https://files.pythonhosted.org/packages/f8/b8/721a9c613641c938a6fb9c7c3efb173b7f77b519de066e9cd2eeb27c3289/audiotsm-0.1.2.tar.gz"; sha256 = "8870af28fad0a76cac1d2bb2b55e7eac6ad5d1ad5416293eb16120dece6c0281"; };
      doCheck = false;
      buildInputs = [];
      propagatedBuildInputs = [
        python.pkgs.numpy
      ];
      meta = with pkgs.lib; {
        homepage = "https://github.com/Muges/audiotsm";
        license = licenses.mit;
        description = "A real-time audio time-scale modification library";
      };
    };

  pythonForThis = python.withPackages (ps: with ps;[
    scipy
    numpy
    pillow
    audiotsm
    gradio
  ]);
  talksReducer = stdenv.mkDerivation {
    pname = "talks-reducer";
    version = "0.0.1";
    src = ./.;
    buildInputs = [
      pythonForThis
      ffmpeg
    ];
    installPhase = ''
      mkdir -p $out/bin $out/lib/python
      cp -r $src/talks_reducer $out/lib/python/
      cat <<'SCRIPT' > $out/bin/talks-reducer
#!${pythonForThis}/bin/python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib', 'python'))
os.environ.setdefault("TALKS_REDUCER_FFMPEG", "${ffmpeg}/bin/ffmpeg")

from talks_reducer.cli import main


if __name__ == "__main__":
    main()
SCRIPT
      chmod +x $out/bin/talks-reducer
    '';
  };
  
  nix-bundle-src = builtins.fetchGit {
    url = "https://github.com/matthewbauer/nix-bundle";
    rev = "e9fa7e8a118942adafa8592a28b301ee23d37c13";
  };
  nix-bundle = (import ("${nix-bundle-src}/appimage-top.nix") {}) // (import "${nix-bundle-src}/default.nix" {});
in
  talksReducer // {
    bundle = nix-bundle.nix-bootstrap {
      extraTargets = [];
      target = talksReducer;
      run = "/bin/talks-reducer";
    };
  }
