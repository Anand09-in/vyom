"use client";
import { Amplify } from "aws-amplify";
import {
  signIn,
  signUp,
  confirmSignUp,
  signOut as amplifySignOut,
  fetchAuthSession,
  getCurrentUser,
} from "aws-amplify/auth";

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID!,
      userPoolClientId: process.env.NEXT_PUBLIC_COGNITO_APP_CLIENT_ID!,
    },
  },
});

/** The Cognito ID token — attached as a Bearer token on every API call.
 * Vyom's backend validates this directly against the user pool's JWKS,
 * see api/auth.py. Returns null if there's no signed-in session. */
export async function getIdToken(): Promise<string | null> {
  try {
    const session = await fetchAuthSession();
    return session.tokens?.idToken?.toString() ?? null;
  } catch {
    return null;
  }
}

export async function isSignedIn(): Promise<boolean> {
  try {
    await getCurrentUser();
    return true;
  } catch {
    return false;
  }
}

export { signIn, signUp, confirmSignUp, amplifySignOut as signOut };
