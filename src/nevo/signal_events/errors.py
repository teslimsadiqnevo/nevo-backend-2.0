class SignalIngestionError(Exception):
    code = "signal_ingestion_error"
    public_message = "Unable to ingest signal events."


class EmptySignalBatchError(SignalIngestionError):
    code = "empty_signal_batch"
    public_message = "At least one signal event is required."


class SignalBatchTooLargeError(SignalIngestionError):
    code = "signal_batch_too_large"
    public_message = "Signal event batches cannot contain more than 100 events."


class SessionMismatchError(SignalIngestionError):
    code = "session_mismatch"
    public_message = "All signal events must belong to the submitted lesson session."

