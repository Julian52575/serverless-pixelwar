# Infra CLIs pinned to exact upstream releases (official binaries), independent
# of the nixpkgs channel. Bump: change the version, then refresh hashes with
# `nix-prefetch-url <url>` + `nix hash convert --to sri`.
{ pkgs }:
let
  inherit (pkgs) lib stdenvNoCC fetchurl;
  system = pkgs.stdenv.hostPlatform.system;

  # Per-system: [ terraform/hashicorp, helm, kubectl (dl.k8s.io), gcloud, zizmor ]
  platforms = {
    x86_64-linux = { tf = "linux_amd64"; helm = "linux-amd64"; k8s = "linux/amd64"; gcloud = "linux-x86_64"; zizmor = "x86_64-unknown-linux-gnu"; };
    aarch64-linux = { tf = "linux_arm64"; helm = "linux-arm64"; k8s = "linux/arm64"; gcloud = "linux-arm"; zizmor = "aarch64-unknown-linux-gnu"; };
    x86_64-darwin = { tf = "darwin_amd64"; helm = "darwin-amd64"; k8s = "darwin/amd64"; gcloud = "darwin-x86_64"; zizmor = "x86_64-apple-darwin"; };
  };
  p = platforms.${system};

  hashes = {
    x86_64-linux = {
      terraform = "sha256-wWjKt8Y3qHaf25AInd0Z3nAbxv+KymTcLiGF/kb1n2c=";
      helm = "sha256-BAOoiuIJE9EbEKJGe1AIdyH+p1gXNtprnTmS9TV/5Us=";
      kubectl = "sha256-ZWkf9362+kTJCLd6EILJ8JLDuXM7XO+r7A0RBIkOIag=";
      gcloud = "sha256-FQOm/NponR4QE6Qh4shYUOf1g4LAvnBkh3teGhA4vGQ=";
      zizmor = "sha256-0YX3Jr2vkt94JzIX390k681rDvSM8853b/V2K24TjJk=";
    };
    aarch64-linux = {
      terraform = "sha256-8yR4E0/8bXEO7EdLvTFmUs3dwPTjNpc6N0Xo06MwnN8=";
      helm = "sha256-jPj2bsvCUqyPfwbMpoq6iFCN3946ajT+sWeK0WlLT4g=";
      kubectl = "sha256-/3SfS3jZxPHshzB9+bUBGe2BniCUqpgQy5rP/DKGyMc=";
      gcloud = "sha256-VHxcKK5EmoYjOe2+c+QlQHOzMHKjZEY/WBrev4lMXPo=";
      zizmor = "sha256-N+671XYqRPJi2Uh1QxsUptJAKZHpCmhRE+qXuLQb6DM=";
    };
    x86_64-darwin = {
      terraform = "sha256-N3M5dSQZbk679xZ+K5+0eN/xli1VXWSfYWupfKRGoUM=";
      helm = "sha256-NL7E66dhulwW0ZZe5rj1sKvlmTl0qAInTipPBBiJPYk=";
      kubectl = "sha256-aFE4HEhv9u3WkWI+PWXIfLmlsCiH/4+7s42KAxt0g4c=";
      gcloud = "sha256-OxOAsxGOm7idwQi26ykeQUaCiUFdzSozzfxV4lcNPt4=";
      zizmor = "sha256-cq5ju4W2cinAYkLwQZXLQ5J+n6tfQ4A8ZDTccBpRfWE=";
    };
  }.${system};
in
rec {
  terraform = stdenvNoCC.mkDerivation rec {
    pname = "terraform";
    version = "1.17.0";
    src = fetchurl {
      url = "https://releases.hashicorp.com/terraform/${version}/terraform_${version}_${p.tf}.zip";
      hash = hashes.terraform;
    };
    nativeBuildInputs = [ pkgs.unzip ];
    sourceRoot = ".";
    installPhase = "install -Dm755 terraform $out/bin/terraform";
  };

  helm = stdenvNoCC.mkDerivation rec {
    pname = "helm";
    version = "4.3.1";
    src = fetchurl {
      url = "https://get.helm.sh/helm-v${version}-${p.helm}.tar.gz";
      hash = hashes.helm;
    };
    installPhase = "install -Dm755 helm $out/bin/helm";
  };

  # Upstream: github.com/kubernetes/kubernetes; binaries served from dl.k8s.io
  kubectl = stdenvNoCC.mkDerivation rec {
    pname = "kubectl";
    version = "1.37.1";
    src = fetchurl {
      url = "https://dl.k8s.io/release/v${version}/bin/${p.k8s}/kubectl";
      hash = hashes.kubectl;
    };
    dontUnpack = true;
    installPhase = "install -Dm755 $src $out/bin/kubectl";
  };

  # Same archive google-github-actions/setup-gcloud installs (rapid channel)
  gcloud = stdenvNoCC.mkDerivation rec {
    pname = "google-cloud-cli";
    version = "590.0.0";
    src = fetchurl {
      url = "https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-${version}-${p.gcloud}.tar.gz";
      hash = hashes.gcloud;
    };
    nativeBuildInputs = [ pkgs.makeWrapper ];
    dontPatchShebangs = true;
    installPhase = ''
      mkdir -p $out/libexec $out/bin
      cp -r . $out/libexec/google-cloud-sdk
      for b in gcloud gsutil bq; do
        makeWrapper $out/libexec/google-cloud-sdk/bin/$b $out/bin/$b \
          --set CLOUDSDK_PYTHON ${pkgs.python3}/bin/python3 \
          --set CLOUDSDK_COMPONENT_MANAGER_DISABLE_UPDATE_CHECK 1
      done
    '';
  };

  # nixpkgs 25.05 ships 1.8.0; CI runs this same version
  zizmor = stdenvNoCC.mkDerivation rec {
    pname = "zizmor";
    version = "1.31.1";
    src = fetchurl {
      url = "https://github.com/zizmorcore/zizmor/releases/download/v${version}/zizmor-${p.zizmor}.tar.gz";
      hash = hashes.zizmor;
    };
    nativeBuildInputs = lib.optional pkgs.stdenv.isLinux pkgs.autoPatchelfHook;
    buildInputs = lib.optional pkgs.stdenv.isLinux pkgs.stdenv.cc.cc.lib;
    sourceRoot = ".";
    installPhase = "install -Dm755 zizmor $out/bin/zizmor";
  };

  # Pins `uses:` refs in workflows to commit SHAs
  pin-github-action = pkgs.buildNpmPackage rec {
    pname = "pin-github-action";
    version = "3.5.2";
    src = pkgs.fetchFromGitHub {
      owner = "mheap";
      repo = "pin-github-action";
      rev = "v${version}";
      hash = "sha256-k29f/8mBNgOjsPejLEn0UiczvawepeQtQjwesPqJPZc=";
    };
    npmDepsHash = "sha256-RlmtwE6AUV6RnAIwGly1pnuLbcLJ7nbUxH6NHX0IGg0=";
    dontNpmBuild = true;
  };

  all = [ terraform helm kubectl gcloud pin-github-action zizmor ];
}
