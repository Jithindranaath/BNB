// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ReceiptAnchor
/// @notice Minimal by design (architecture.md §12). The orchestrator batches
///         receipt merkle leaves every ~10 minutes, computes the root, and calls
///         `anchor`. The UI verifies a per-receipt proof against the emitted root.
///         This is what turns "trust our dashboard" into "verify the hash".
contract ReceiptAnchor {
    address public owner;
    mapping(address => bool) public isWriter;

    event WriterSet(address indexed writer, bool allowed);
    event BatchAnchored(uint256 indexed batchId, bytes32 root, uint256 count, uint256 ts);

    error NotOwner();
    error NotWriter();

    constructor() {
        owner = msg.sender;
        isWriter[msg.sender] = true;
        emit WriterSet(msg.sender, true);
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    function setWriter(address writer, bool allowed) external onlyOwner {
        isWriter[writer] = allowed;
        emit WriterSet(writer, allowed);
    }

    /// @param batchId monotonic batch counter from the orchestrator
    /// @param root    merkle root over the batch's receipt leaves
    /// @param count   number of leaves in the batch
    function anchor(uint256 batchId, bytes32 root, uint256 count) external {
        if (!isWriter[msg.sender]) revert NotWriter();
        emit BatchAnchored(batchId, root, count, block.timestamp);
    }
}
