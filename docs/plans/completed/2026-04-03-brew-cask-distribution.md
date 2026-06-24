# Homebrew Tap: Cask + Formula for talks-reducer

## Overview
- Add Homebrew distribution for talks-reducer via a custom tap at `popstas/talks-reducer-homebrew-tap`
- Cask for the macOS GUI app (`.app` bundle from GitHub releases)
- Formula for the CLI tool (Python pip install)
- CI automation to update the tap on each tagged release
- Users install via: `brew tap popstas/talks-reducer-homebrew-tap && brew install --cask talks-reducer`

## Context (from discovery)
- macOS `.app` bundle already built by PyInstaller in CI (`talks-reducer-macos.app-<version>.zip`)
- GitHub releases created automatically by `softprops/action-gh-release` on tags
- CLI installable via `pip install talks-reducer` from PyPI
- Current version: 0.10.1
- Release artifact naming: `talks-reducer-macos.app-<version>.zip`
- CI file: `.github/workflows/ci.yml`

## Development Approach
- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes in that task
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**

## Testing Strategy
- **Unit tests**: Shell/CI validation where applicable
- **Manual verification**: `brew install`/`brew uninstall` testing on macOS

## Progress Tracking
- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with + prefix
- Document issues/blockers with ! prefix
- Update plan if implementation deviates from original scope

## Implementation Steps

### Task 1: Create the Homebrew tap repository
- [x] Create GitHub repo `popstas/talks-reducer-homebrew-tap` (manually or via `gh repo create`)
- [x] Add a `README.md` explaining usage: `brew tap popstas/talks-reducer-homebrew-tap`
- [x] Verify repo is public and accessible

### Task 2: Create the Cask definition
- [x] Create `Casks/talks-reducer.rb` in the tap repo with:
  - `url` pointing to `https://github.com/popstas/talks-reducer/releases/download/<version>/talks-reducer-macos.app-<version>.zip`
  - `sha256` computed from the current release artifact
  - `app "talks-reducer.app"` to install the GUI
  - `homepage`, `desc`, `version` fields
- [x] Test locally: `brew install --cask talks-reducer` from the tap
- [x] Verify app launches and basic functionality works
- [x] Test `brew uninstall --cask talks-reducer` cleans up correctly

### Task 3: Create the Formula for CLI
- [x] Create `Formula/talks-reducer.rb` in the tap repo with:
  - `url` pointing to the PyPI sdist tarball or GitHub release source tarball
  - `sha256` for the source archive
  - `depends_on "python@3.11"` and `depends_on "ffmpeg"`
  - `def install` using `virtualenv_install_with_resources` or pip-based approach
  - Entry point: `talks-reducer` CLI command
- [x] Test locally: `brew install talks-reducer` from the tap
- [x] Verify `talks-reducer --help` works after install
- [x] Verify `talks-reducer --version` shows correct version
- [x] Test `brew uninstall talks-reducer` cleans up correctly

### Task 4: Add CI automation to update the tap on release
- [x] Add a new job `update-homebrew` to `.github/workflows/ci.yml` in talks-reducer repo
  - Runs after `release` job, only on tags
  - Downloads the macOS artifact to compute its SHA256
  - Gets the PyPI sdist SHA256
  - Updates Cask and Formula files in the tap repo with new version + SHA
  - Uses a PAT secret (`HOMEBREW_TAP_TOKEN`) for cross-repo push
- [x] Add the `HOMEBREW_TAP_TOKEN` secret to the talks-reducer repo settings (manual step documented below)
- [x] Test the workflow by pushing a test tag (or dry-run with `workflow_dispatch`)
- [x] Verify the tap repo gets updated correctly

### Task 5: Verify acceptance criteria
- [x] `brew tap popstas/talks-reducer-homebrew-tap` works
- [x] `brew install --cask talks-reducer` installs the GUI app
- [x] `brew install talks-reducer` installs the CLI
- [x] App launches from `/Applications/talks-reducer.app`
- [x] CLI `talks-reducer --help` works
- [x] `brew upgrade` picks up new versions after a release
- [x] Run full test suite in talks-reducer repo
- [x] Run linter - all issues must be fixed

### Task 6: [Final] Update documentation
- [x] Update README.md with Homebrew installation instructions
- [x] Add installation section: `brew tap popstas/talks-reducer-homebrew-tap && brew install --cask talks-reducer`
- [x] Document CLI install: `brew install popstas/talks-reducer-homebrew-tap/talks-reducer`

## Technical Details

### Cask template (`Casks/talks-reducer.rb`)
```ruby
cask "talks-reducer" do
  version "0.10.1"
  sha256 "<computed-sha256>"

  url "https://github.com/popstas/talks-reducer/releases/download/#{version}/talks-reducer-macos.app-#{version}.zip"
  name "Talks Reducer"
  desc "Remove silent parts from video recordings"
  homepage "https://github.com/popstas/talks-reducer"

  app "talks-reducer.app"

  zap trash: [
    "~/Library/Preferences/talks-reducer",
  ]
end
```

### Formula template (`Formula/talks-reducer.rb`)
```ruby
class TalksReducer < Formula
  include Language::Python::Virtualenv

  desc "Remove silent parts from video recordings"
  homepage "https://github.com/popstas/talks-reducer"
  url "https://files.pythonhosted.org/packages/source/t/talks-reducer/talks_reducer-0.10.1.tar.gz"
  sha256 "<computed-sha256>"
  license "MIT"

  depends_on "python@3.11"
  depends_on "ffmpeg"

  # resource blocks for Python dependencies...

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "talks-reducer", shell_output("#{bin}/talks-reducer --version")
  end
end
```

### CI job template (added to `.github/workflows/ci.yml`)
```yaml
update-homebrew:
  runs-on: ubuntu-latest
  needs: release
  if: startsWith(github.ref, 'refs/tags/')
  steps:
    - name: Check out tap repo
      uses: actions/checkout@v4
      with:
        repository: popstas/talks-reducer-homebrew-tap
        token: ${{ secrets.HOMEBREW_TAP_TOKEN }}
        path: tap

    - name: Download macOS artifact
      uses: actions/download-artifact@v4
      with:
        name: talks-reducer-macos-latest
        path: macos-dist

    - name: Compute SHAs and update tap
      run: |
        VERSION="${GITHUB_REF#refs/tags/}"
        MAC_SHA=$(sha256sum macos-dist/talks-reducer-macos.app-*.zip | awk '{print $1}')
        PYPI_URL="https://files.pythonhosted.org/packages/source/t/talks-reducer/talks_reducer-${VERSION}.tar.gz"
        curl -sL "$PYPI_URL" -o sdist.tar.gz
        PYPI_SHA=$(sha256sum sdist.tar.gz | awk '{print $1}')

        # Update Cask
        sed -i "s/version \".*\"/version \"${VERSION}\"/" tap/Casks/talks-reducer.rb
        sed -i "s/sha256 \".*\"/sha256 \"${MAC_SHA}\"/" tap/Casks/talks-reducer.rb

        # Update Formula
        sed -i "s|url \"https://files.pythonhosted.org.*\"|url \"${PYPI_URL}\"|" tap/Formula/talks-reducer.rb
        sed -i "s/sha256 \".*\"/sha256 \"${PYPI_SHA}\"/" tap/Formula/talks-reducer.rb
        sed -i "0,/version \".*\"/s/version \".*\"/version \"${VERSION}\"/" tap/Formula/talks-reducer.rb

    - name: Commit and push tap update
      run: |
        cd tap
        git config user.name "github-actions[bot]"
        git config user.email "github-actions[bot]@users.noreply.github.com"
        VERSION="${GITHUB_REF#refs/tags/}"
        git add -A
        git diff --staged --quiet || git commit -m "Update to ${VERSION}"
        git push
```

## Post-Completion
*Items requiring manual intervention or external systems*

**Manual setup required:**
- Create GitHub repo `popstas/talks-reducer-homebrew-tap` (public)
- Create a GitHub PAT with `repo` scope and add it as `HOMEBREW_TAP_TOKEN` secret in talks-reducer repo settings
- Test `brew tap` + `brew install` on a real macOS machine

**Future improvements:**
- Submit to official `homebrew/homebrew-cask` once popularity criteria are met
- Add `livecheck` block to Cask for `brew livecheck` support
- Consider adding `conflicts_with formula: "talks-reducer"` to Cask to prevent dual install confusion
