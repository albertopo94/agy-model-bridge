"""Unit tests for centralized error hierarchy and backward compatibility."""

import unittest

import bridge.errors as errors


class TestBridgeErrors(unittest.TestCase):
    """Verifies exception inheritance and properties in bridge.errors."""

    def test_base_error_inherits_exception(self):
        self.assertTrue(issubclass(errors.BridgeError, Exception))
        err = errors.BridgeError("base error")
        self.assertIsInstance(err, Exception)
        self.assertEqual(str(err), "base error")

    def test_all_specialized_errors_inherit_bridge_error(self):
        expected_subclasses = [
            errors.AuthenticationError,
            errors.ForbiddenError,
            errors.InvalidRequestError,
            errors.ModelNotFoundError,
            errors.RateLimitError,
            errors.CapacityExhaustedError,
            errors.UpstreamTimeoutError,
            errors.UpstreamError,
            errors.ProtocolError,
        ]
        for exc_cls in expected_subclasses:
            with self.subTest(exc_cls=exc_cls.__name__):
                self.assertTrue(
                    issubclass(exc_cls, errors.BridgeError),
                    f"{exc_cls.__name__} must inherit from BridgeError",
                )
                inst = exc_cls(f"test {exc_cls.__name__}")
                self.assertIsInstance(inst, errors.BridgeError)

    def test_upstream_error_attributes(self):
        err = errors.UpstreamError("Gateway error", status_code=502)
        self.assertEqual(str(err), "Gateway error")
        self.assertEqual(err.status_code, 502)
        self.assertIsInstance(err, errors.BridgeError)

        err_default = errors.UpstreamError("Default upstream error")
        self.assertEqual(str(err_default), "Default upstream error")
        self.assertIsNone(err_default.status_code)

    def test_client_reexports_backward_compatibility(self):
        import bridge.client as client

        reexported_errors = [
            ("BridgeError", errors.BridgeError),
            ("AuthenticationError", errors.AuthenticationError),
            ("ForbiddenError", errors.ForbiddenError),
            ("InvalidRequestError", errors.InvalidRequestError),
            ("ModelNotFoundError", errors.ModelNotFoundError),
            ("RateLimitError", errors.RateLimitError),
            ("CapacityExhaustedError", errors.CapacityExhaustedError),
            ("UpstreamTimeoutError", errors.UpstreamTimeoutError),
            ("UpstreamError", errors.UpstreamError),
        ]
        for name, expected_cls in reexported_errors:
            with self.subTest(name=name):
                self.assertTrue(hasattr(client, name), f"bridge.client must export {name}")
                self.assertIs(getattr(client, name), expected_cls)

    def test_auth_reexports_backward_compatibility(self):
        import bridge.auth as auth

        self.assertTrue(hasattr(auth, "AuthenticationError"))
        self.assertIs(auth.AuthenticationError, errors.AuthenticationError)


if __name__ == "__main__":
    unittest.main()
