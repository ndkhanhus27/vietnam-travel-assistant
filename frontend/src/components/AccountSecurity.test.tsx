// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import { AccountSecurity } from "./AccountSecurity";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("Account security", () => {
  it("shows Google-only sign in without a create-password form", async () => {
    vi.spyOn(api, "authMethods").mockResolvedValue({ has_password: false, google_linked: true });
    render(<AccountSecurity email="user@gmail.com" />);
    await screen.findByText("Google");
    expect(screen.queryByRole("button", { name: "Đổi mật khẩu" })).toBeNull();
    expect(screen.queryByText("Tạo mật khẩu đăng nhập")).toBeNull();
    expect(screen.queryByLabelText("Mật khẩu mới")).toBeNull();
  });

  it("requests an email confirmation before changing an existing password", async () => {
    vi.spyOn(api, "authMethods").mockResolvedValue({ has_password: true, google_linked: false });
    const request = vi.spyOn(api, "forgotPassword").mockResolvedValue({ message: "Check email" });
    render(<AccountSecurity email="user@gmail.com" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Đổi mật khẩu" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("user@gmail.com"));
    expect(screen.getByRole("status").textContent).toContain("kiểm tra Gmail");
    expect((screen.getByRole("button", { name: "Đã gửi yêu cầu" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("does not invent a password method when the API is unavailable", async () => {
    vi.spyOn(api, "authMethods").mockRejectedValue(new Error("Unavailable"));
    render(<AccountSecurity email="user@gmail.com" />);
    await screen.findByRole("alert");
    expect(screen.queryByRole("button", { name: "Đổi mật khẩu" })).toBeNull();
  });
});
