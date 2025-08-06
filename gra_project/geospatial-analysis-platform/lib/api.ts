export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";

/**
 * A generic fetch wrapper for making API calls.
 * @param endpoint The API endpoint to call (e.g., '/plan/').
 * @param options The options for the fetch request (method, headers, body, etc.).
 * @returns The JSON response from the API.
 * @throws An error if the network response is not ok.
 */
export async function apiService<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

  const defaultHeaders = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  const config: RequestInit = {
    ...options,
    headers: defaultHeaders,
  };

  try {
    const response = await fetch(url, config);

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: 'An unknown error occurred.' }));
      throw new Error(errorData.detail || errorData.message || `HTTP error! status: ${response.status}`);
    }
    
    // Handle cases where the response might be empty (e.g., 204 No Content)
    const contentType = response.headers.get("content-type");
    if (contentType && contentType.indexOf("application/json") !== -1) {
        return await response.json() as T;
    } else {
        return null as T; // Or handle as appropriate for your app
    }

  } catch (error) {
    console.error('API Service Error:', error);
    throw error;
  }
}
