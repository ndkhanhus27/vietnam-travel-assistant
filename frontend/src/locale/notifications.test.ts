import { describe, expect, it } from "vitest";
import { localizeNotification } from "./notifications";

describe("public notifications", () => {
  it("keeps backend errors and Google notices in Vietnamese", () => {
    expect(localizeNotification("Email hoặc mật khẩu không đúng")).toBe("Email hoặc mật khẩu không đúng");
    expect(localizeNotification("Could not load Google sign-in.")).toBe("Không thể tải tính năng đăng nhập bằng Google.");
  });
  it("translates an existing error after switching language", () => {
    expect(localizeNotification("Your session has expired.")).toBe("Phiên đăng nhập đã hết hạn.");
  });
});
