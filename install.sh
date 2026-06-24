#!/usr/bin/env bash
# chatgpt-pwm installer
set -e

REPO="integritynoble/ChatGPT_PWM"
BIN_NAME="chatgpt-pwm"

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Linux)
    case "$ARCH" in
      x86_64) ASSET="chatgpt-pwm-linux-x86_64" ;;
      aarch64|arm64) ASSET="chatgpt-pwm-linux-arm64" ;;
      *) ASSET="" ;;
    esac
    INSTALL_DIR="/usr/local/bin"
    ;;
  Darwin)
    case "$ARCH" in
      arm64) ASSET="chatgpt-pwm-macos-arm64" ;;
      x86_64) ASSET="chatgpt-pwm-macos-x86_64" ;;
      *) ASSET="" ;;
    esac
    INSTALL_DIR="/usr/local/bin"
    ;;
  *)
    ASSET=""
    ;;
esac

if [ -z "$ASSET" ]; then
  echo "No pre-built binary for $OS/$ARCH — installing via pip..."
  pip install --upgrade chatgpt-pwm
  exit 0
fi

URL="https://github.com/$REPO/releases/latest/download/$ASSET"
TMP="$(mktemp)"

echo "Downloading $ASSET..."
curl -fsSL "$URL" -o "$TMP"
chmod +x "$TMP"

echo "Installing to $INSTALL_DIR/$BIN_NAME..."
if [ -w "$INSTALL_DIR" ]; then
  mv "$TMP" "$INSTALL_DIR/$BIN_NAME"
else
  sudo mv "$TMP" "$INSTALL_DIR/$BIN_NAME"
fi

echo ""
echo "✓ chatgpt-pwm installed!"
echo ""
echo "Sign in with your ChatGPT account and start chatting:"
echo ""
echo "  chatgpt-pwm login"
echo "  chatgpt-pwm"
