// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { AuthPage } from "./AuthPage";
import { PasswordRecoveryPage } from "./PasswordRecoveryPage";
import { api, ApiError, sessionStore } from "../api/client";

const authenticate = vi.hoisted(() => vi.fn());
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ authenticate }) }));
vi.mock("../components/GoogleSignIn", () => ({ GoogleSignIn: ({ onCredential }: { onCredential: (credential: string) => void }) => <button onClick={() => onCredential("google-token")}>Google test</button> }));

beforeEach(() => { vi.restoreAllMocks(); authenticate.mockClear(); window.history.replaceState(null, "", "/"); });
afterEach(cleanup);

function show(page: React.ReactNode) { return render(<MemoryRouter>{page}</MemoryRouter>); }

describe("Authentication user flows", () => {
  it("collects Gmail first, then submits the password", async () => {
    const user = userEvent.setup();
    const login = vi.spyOn(api, "login").mockResolvedValue({ user: { id: "existing" } } as never);
    show(<AuthPage mode="login" />);
    expect(screen.queryByLabelText("Mật khẩu")).toBeNull();
    await user.type(screen.getByLabelText("Địa chỉ Gmail"), "User@GMAIL.COM");
    await user.click(screen.getByRole("button", { name: "Tiếp tục" }));
    expect(login).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Mật khẩu"), "Password123!");
    await user.click(screen.getByRole("button", { name: "Tiếp tục" }));
    await waitFor(() => expect(login).toHaveBeenCalledWith({ email: "user@gmail.com", password: "Password123!" }));
  });

  it("rejects Outlook before proceeding to the password step", async () => {
    const user = userEvent.setup();
    show(<AuthPage mode="login" />);
    await user.type(screen.getByLabelText("Địa chỉ Gmail"), "user@outlook.com");
    await user.click(screen.getByRole("button", { name: "Tiếp tục" }));
    expect(screen.getByRole("alert").textContent).toContain("@gmail.com");
    expect(screen.queryByLabelText("Mật khẩu")).toBeNull();
  });

  it("lets the user edit Gmail before submitting a password", async () => {
    const user = userEvent.setup();
    show(<AuthPage mode="login" />);
    await user.type(screen.getByLabelText("Địa chỉ Gmail"), "user@gmail.com");
    await user.click(screen.getByRole("button", { name: "Tiếp tục" }));
    await user.click(screen.getByRole("button", { name: "Thay đổi" }));
    expect((screen.getByLabelText("Địa chỉ Gmail") as HTMLInputElement).value).toBe("user@gmail.com");
  });

  it("registers through the Gmail step and password confirmation", async () => {
    const user = userEvent.setup();
    const register = vi.spyOn(api, "register").mockResolvedValue({ user: { id: "new" } } as never);
    show(<AuthPage mode="register" />);
    await user.type(screen.getByLabelText("Địa chỉ Gmail"), "new@gmail.com");
    await user.click(screen.getByRole("button", { name: "Tiếp tục" }));
    await user.type(screen.getByLabelText("Mật khẩu", { exact: true }), "Password123!");
    await user.type(screen.getByLabelText("Xác nhận mật khẩu"), "Password123!");
    await user.click(screen.getByRole("button", { name: "Tiếp tục" }));
    await waitFor(() => expect(register).toHaveBeenCalledWith({ email: "new@gmail.com", password: "Password123!", display_name: null }));
  });
  it("confirms the local password before linking Google, then authenticates", async () => {
    const user = userEvent.setup();
    const google = vi.spyOn(api, "googleLogin").mockRejectedValueOnce(new ApiError(409, "Confirm password")).mockResolvedValueOnce({ user: { id: "same-user" } } as never);
    show(<AuthPage mode="login" />);
    await user.click(screen.getByText("Google test"));
    await screen.findByRole("button", { name: "Xác nhận liên kết Google" });
    await user.type(screen.getByLabelText("Mật khẩu"), "Password123!");
    await user.click(screen.getByRole("button", { name: "Xác nhận liên kết Google" }));
    await waitFor(() => expect(authenticate).toHaveBeenCalledOnce());
    expect(google).toHaveBeenLastCalledWith("google-token", "Password123!");
  });

  it("keeps the confirmation form after an incorrect password", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "googleLogin").mockRejectedValueOnce(new ApiError(409, "Confirm password")).mockRejectedValueOnce(new ApiError(401, "Invalid password"));
    show(<AuthPage mode="login" />);
    await user.click(screen.getByText("Google test"));
    await screen.findByRole("button", { name: "Xác nhận liên kết Google" });
    await user.type(screen.getByLabelText("Mật khẩu"), "WrongPassword123!");
    await user.click(screen.getByRole("button", { name: "Xác nhận liên kết Google" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("không đúng"));
    expect(authenticate).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Quên mật khẩu?" }).getAttribute("href")).toBe("/forgot-password");
  });

  it("shows the generic email confirmation after requesting recovery", async () => {
    const user = userEvent.setup();
    const forgot = vi.spyOn(api, "forgotPassword").mockResolvedValue({ message: "Nếu email có tài khoản, bạn sẽ nhận được liên kết." });
    show(<PasswordRecoveryPage />);
    await user.type(screen.getByLabelText("Địa chỉ Gmail"), "user@gmail.com");
    await user.click(screen.getByRole("button", { name: "Gửi liên kết xác nhận" }));
    await screen.findByRole("status");
    expect(forgot).toHaveBeenCalledWith("user@gmail.com");
  });

  it("resets with the fragment token and requires a new login", async () => {
    window.history.replaceState(null, "", "/reset-password#token=secret-token");
    const user = userEvent.setup();
    const reset = vi.spyOn(api, "resetPassword").mockResolvedValue();
    const clear = vi.spyOn(sessionStore, "clear").mockImplementation(() => {});
    show(<PasswordRecoveryPage reset />);
    expect(window.location.hash).toBe("");
    await user.type(screen.getByLabelText("Mật khẩu mới"), "Password123!");
    await user.type(screen.getByLabelText("Xác nhận mật khẩu"), "Password123!");
    await user.click(screen.getByRole("button", { name: "Lưu mật khẩu mới" }));
    await screen.findByRole("status");
    expect(reset).toHaveBeenCalledWith("secret-token", "Password123!", "Password123!");
    expect(clear).toHaveBeenCalledOnce();
    expect(authenticate).not.toHaveBeenCalled();
  });

  it("rejects mismatched passwords without calling the API", async () => {
    window.history.replaceState(null, "", "/reset-password#token=secret-token");
    const user = userEvent.setup();
    const reset = vi.spyOn(api, "resetPassword");
    show(<PasswordRecoveryPage reset />);
    await user.type(screen.getByLabelText("Mật khẩu mới"), "Password123!");
    await user.type(screen.getByLabelText("Xác nhận mật khẩu"), "Different123!");
    await user.click(screen.getByRole("button", { name: "Lưu mật khẩu mới" }));
    expect(screen.getByRole("alert").textContent).toContain("không khớp");
    expect(reset).not.toHaveBeenCalled();
  });

  it("shows an expired-token error and offers a new link", async () => {
    window.history.replaceState(null, "", "/reset-password#token=expired");
    const user = userEvent.setup();
    vi.spyOn(api, "resetPassword").mockRejectedValue(new ApiError(400, "Liên kết đã hết hạn"));
    show(<PasswordRecoveryPage reset />);
    await user.type(screen.getByLabelText("Mật khẩu mới"), "Password123!");
    await user.type(screen.getByLabelText("Xác nhận mật khẩu"), "Password123!");
    await user.click(screen.getByRole("button", { name: "Lưu mật khẩu mới" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("hết hạn"));
    expect(screen.getByRole("link", { name: "Yêu cầu liên kết mới" })).toBeTruthy();
  });
});
