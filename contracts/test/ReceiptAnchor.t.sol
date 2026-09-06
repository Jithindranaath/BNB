// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ReceiptAnchor} from "../src/ReceiptAnchor.sol";

// No forge-std dependency yet — kept vendor-free so `forge test` passes on a
// clean clone. T-062 adds forge-std and event-level assertions.
contract ReceiptAnchorTest {
    ReceiptAnchor internal anchor;

    function setUp() public {
        anchor = new ReceiptAnchor();
    }

    function testDeployerIsOwnerAndWriter() public view {
        require(anchor.owner() == address(this), "deployer should be owner");
        require(anchor.isWriter(address(this)), "deployer should be a writer");
    }

    function testWriterCanAnchor() public {
        anchor.anchor(1, keccak256("root-1"), 7);
    }

    function testNonWriterCannotAnchor() public {
        Outsider outsider = new Outsider(anchor);
        (bool ok, ) = address(outsider).call(abi.encodeWithSignature("tryAnchor()"));
        require(!ok, "non-writer must not be able to anchor");
    }

    function testOwnerCanGrantWriter() public {
        Outsider outsider = new Outsider(anchor);
        anchor.setWriter(address(outsider), true);
        (bool ok, ) = address(outsider).call(abi.encodeWithSignature("tryAnchor()"));
        require(ok, "granted writer should be able to anchor");
    }
}

contract Outsider {
    ReceiptAnchor internal anchor;

    constructor(ReceiptAnchor a) {
        anchor = a;
    }

    function tryAnchor() external {
        anchor.anchor(99, bytes32(0), 1);
    }
}
