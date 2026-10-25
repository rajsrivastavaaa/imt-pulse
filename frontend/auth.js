// Cognito sign-up / sign-in without any SDK: plain calls to the Cognito user pool API.
// Tokens live in localStorage; the long-lived refresh token keeps people signed in for a year.
(function () {
  const C = window.PULSE_CONFIG;
  const KEY = "pulse.session";
  const endpoint = `https://cognito-idp.${C.region}.amazonaws.com/`;

  async function cognito(target, body) {
    const r = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "AWSCognitoIdentityProviderService." + target,
      },
      body: JSON.stringify({ ClientId: C.userPoolClientId, ...body }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const err = new Error(friendly(data.__type || "", data.message || "Something went wrong"));
      err.code = (data.__type || "").split("#").pop();
      throw err;
    }
    return data;
  }

  function friendly(type, msg) {
    // Pre-sign-up trigger errors arrive as "PreSignUp failed with error <our message>."
    const m = msg.match(/PreSignUp failed with error (.*?)\.?$/);
    if (m) return m[1];
    if (type.includes("UsernameExists")) return "An account with this email already exists. Try signing in.";
    if (type.includes("NotAuthorized")) return "Wrong email or password.";
    if (type.includes("CodeMismatch")) return "That code is not right. Check the latest email.";
    if (type.includes("ExpiredCode")) return "That code has expired. Request a new one.";
    if (type.includes("InvalidPassword")) return "Password must be at least 8 characters and include a number.";
    if (type.includes("LimitExceeded") || type.includes("TooManyRequests"))
      return "Too many attempts. Please wait a few minutes and try again.";
    return msg;
  }

  function decode(jwt) {
    const p = jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(decodeURIComponent(escape(atob(p))));
  }

  function save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  function load() { try { return JSON.parse(localStorage.getItem(KEY)); } catch (e) { return null; } }

  function store(result, email, refresh) {
    const claims = decode(result.IdToken);
    const s = { id: result.IdToken, refresh: result.RefreshToken || refresh, exp: claims.exp * 1000, email };
    save(s);
    return s;
  }

  function batchFromEmail(email) {
    const m = email.split("@")[0].toLowerCase().match(/^([a-z]+\d{2})/);
    return m ? m[1] : "";
  }

  let refreshing = null;

  window.Auth = {
    batchFromEmail,
    signedIn: () => !!(load() && load().refresh),
    email: () => (load() || {}).email,
    claims: () => { const s = load(); return s ? decode(s.id) : {}; },

    async signUp(email, password, first, last) {
      email = email.trim().toLowerCase();
      const attrs = [
        { Name: "email", Value: email },
        { Name: "given_name", Value: first.trim() },
        { Name: "family_name", Value: last.trim() },
      ];
      const batch = batchFromEmail(email);
      if (batch) attrs.push({ Name: "custom:batch", Value: batch });
      return cognito("SignUp", { Username: email, Password: password, UserAttributes: attrs });
    },
    confirm: (email, code) => cognito("ConfirmSignUp", { Username: email.trim().toLowerCase(), ConfirmationCode: code.trim() }),
    resend: (email) => cognito("ResendConfirmationCode", { Username: email.trim().toLowerCase() }),
    forgot: (email) => cognito("ForgotPassword", { Username: email.trim().toLowerCase() }),
    resetPassword: (email, code, password) => cognito("ConfirmForgotPassword",
      { Username: email.trim().toLowerCase(), ConfirmationCode: code.trim(), Password: password }),

    async signIn(email, password) {
      email = email.trim().toLowerCase();
      const r = await cognito("InitiateAuth", {
        AuthFlow: "USER_PASSWORD_AUTH", AuthParameters: { USERNAME: email, PASSWORD: password },
      });
      return store(r.AuthenticationResult, email);
    },

    // Returns a valid ID token, refreshing it if it expires within a minute.
    async idToken(force) {
      const s = load();
      if (!s) throw new Error("signed out");
      if (!force && s.exp - Date.now() > 60000) return s.id;
      if (!refreshing) {
        refreshing = cognito("InitiateAuth", {
          AuthFlow: "REFRESH_TOKEN_AUTH", AuthParameters: { REFRESH_TOKEN: s.refresh },
        }).then((r) => store(r.AuthenticationResult, s.email, s.refresh).id)
          .catch((e) => { if (e.code === "NotAuthorizedException") Auth.clear(); throw e; })
          .finally(() => { refreshing = null; });
      }
      return refreshing;
    },

    clear() { try { localStorage.removeItem(KEY); } catch (e) {} },

    async signOut() {
      const s = load();
      if (s && s.refresh) await cognito("RevokeToken", { Token: s.refresh }).catch(() => {});
      Auth.clear();
    },
  };
})();
