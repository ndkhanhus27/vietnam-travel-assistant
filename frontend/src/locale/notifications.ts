const messages: Array<[string, string]> = [
  ["Yêu cầu không thành công. Vui lòng thử lại.", "The request failed. Please try again."],
  ["Trợ lý chưa thể hoàn tất câu trả lời.", "The assistant could not complete the answer."],
  ["Dịch vụ đang tạm thời gián đoạn.", "The service is temporarily unavailable."],
  ["Bạn thao tác quá nhanh. Vui lòng thử lại sau.", "Too many requests. Please try again later."],
  ["Không thể kết nối đến máy chủ. Vui lòng kiểm tra kết nối mạng.", "Could not connect to the server. Check your connection."],
  ["Phiên đăng nhập đã hết hạn.", "Your session has expired."],
  ["Máy chủ không trả về nội dung phản hồi.", "The server returned no response."],
  ["Kết nối bị gián đoạn trước khi trợ lý trả về kết quả.", "The connection was interrupted before the answer was received."],
  ["Email này đã được đăng ký", "This email is already registered."],
  ["Email này đã có tài khoản. Xác nhận mật khẩu để liên kết Google, hoặc chọn Quên mật khẩu.", "This email already has an account. Confirm your password to link Google, or choose Forgot password."],
  ["Email hoặc mật khẩu không đúng", "Incorrect email or password."],
  ["Tài khoản đã bị vô hiệu hoá", "This account is disabled."],
  ["Địa chỉ email không hợp lệ", "Invalid email address."],
  ["Mật khẩu phải có từ 8 đến 128 ký tự", "The password must contain 8 to 128 characters."],
  ["Tài khoản đã có mật khẩu đăng nhập", "This account already has a password."],
  ["Phiên đăng nhập không hợp lệ hoặc đã hết hạn", "Your session is invalid or expired."],
  ["Liên kết đặt lại mật khẩu không hợp lệ, đã hết hạn hoặc đã dùng. Hãy yêu cầu liên kết mới.", "This reset link is invalid, expired or already used. Request a new link."],
  ["Chỉ hỗ trợ địa chỉ @gmail.com. Vui lòng sử dụng tài khoản Gmail.", "Only @gmail.com addresses are supported. Use your Gmail account."],
  ["Thông tin đăng nhập Google không hợp lệ", "Invalid Google sign-in credentials."],
  ["Không tìm thấy cuộc trò chuyện", "Conversation not found."],
  ["Nội dung tin nhắn không hợp lệ", "Invalid message content."],
  ["Đăng nhập bằng Google chưa được cấu hình cho bản triển khai này.", "Google sign-in is not configured."],
  ["Đăng nhập bằng Google chỉ khả dụng trên tên miền HTTPS hoặc localhost.", "Google sign-in requires HTTPS or localhost."],
  ["Google không trả về thông tin đăng nhập. Vui lòng thử lại.", "Google returned no credentials. Please try again."],
  ["Không thể tải tính năng đăng nhập bằng Google.", "Could not load Google sign-in."],
];

export function localizeNotification(message: string) {
  const pair = messages.find(([vi, en]) => message === vi || message === en);
  return pair ? pair[0] : message;
}
