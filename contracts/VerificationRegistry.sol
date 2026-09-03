// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @title VerificationRegistry
/// @notice Tamper-evident registry of face-verification records.
///
/// Only a SHA-256 digest of the canonical verification record is stored, plus
/// two small public metadata fields. Deliberately NOT stored on-chain: face
/// images, face embeddings, biometric data of any kind, or personal information.
/// Anyone can recompute the digest from the off-chain record and compare it with
/// what is stored here.
///
/// What this contract proves: the record committed at a given block has not
/// changed since. What it does not prove: that the underlying claim was true.
contract VerificationRegistry {
    struct Record {
        bytes32 recordHash;     // SHA-256 of the canonical JSON record
        uint64 blockTimestamp;  // when it was committed
        address submitter;      // who committed it
        string source;          // platform label, e.g. "Reddit"
        string candidateUrl;    // public URL of the discovered post
    }

    /// @dev Keyed by the record hash: the digest is the identity of the record.
    mapping(bytes32 => Record) private _records;

    uint256 public recordCount;

    event VerificationRegistered(
        bytes32 indexed recordHash,
        address indexed submitter,
        uint64 blockTimestamp,
        string source,
        string candidateUrl
    );

    error EmptyRecordHash();
    error RecordAlreadyExists(bytes32 recordHash);
    error RecordNotFound(bytes32 recordHash);

    /// @notice Commit a verification record hash.
    /// @param recordHash SHA-256 digest of the canonical JSON record.
    /// @param source Platform label of the discovered post.
    /// @param candidateUrl Public URL of the discovered post.
    function registerVerification(
        bytes32 recordHash,
        string calldata source,
        string calldata candidateUrl
    ) external {
        if (recordHash == bytes32(0)) revert EmptyRecordHash();
        // Immutable once written: re-registering the same digest must not be
        // able to overwrite the original timestamp or submitter.
        if (_records[recordHash].recordHash != bytes32(0)) {
            revert RecordAlreadyExists(recordHash);
        }

        uint64 ts = uint64(block.timestamp);
        _records[recordHash] = Record({
            recordHash: recordHash,
            blockTimestamp: ts,
            submitter: msg.sender,
            source: source,
            candidateUrl: candidateUrl
        });
        unchecked {
            ++recordCount;
        }

        emit VerificationRegistered(recordHash, msg.sender, ts, source, candidateUrl);
    }

    /// @notice Read a record back. Reverts if the hash was never registered.
    function getRecord(bytes32 recordHash) external view returns (Record memory) {
        Record memory record = _records[recordHash];
        if (record.recordHash == bytes32(0)) revert RecordNotFound(recordHash);
        return record;
    }

    /// @notice Whether a record hash has been committed. Never reverts.
    function isRegistered(bytes32 recordHash) external view returns (bool) {
        return _records[recordHash].recordHash != bytes32(0);
    }
}
