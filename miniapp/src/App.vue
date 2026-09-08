<script>
export default {
  onLaunch() {
    // The backend remains the source of truth for authentication.  Keeping
    // only the bearer token locally lets a user return to the same chat
    // without storing message content in the mini-program storage.
  },
}
</script>

<style>
page {
  color: #243a39;
  background: #f7faf9;
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
  font-size: 28rpx;
}

view, text, button, input, textarea, scroll-view {
  box-sizing: border-box;
}

button::after {
  border: 0;
}
</style>
