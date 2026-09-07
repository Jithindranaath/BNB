// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title HoneypotToken — a deliberately malicious ERC-20 used ONLY as a test
///        fixture for the bsc-sentry fork simulation (T-030). It lets anyone buy
///        but reverts on sells (transfers into the DEX pair) from non-owners.
///        Never deployed to any live network.
contract HoneypotToken {
    string public name = "Honeypot Test Token";
    string public symbol = "HPT";
    uint8 public constant decimals = 18;
    uint256 public totalSupply;

    address public owner;
    address public pair; // once set, transfers INTO it from non-owners revert

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor(uint256 supply) {
        owner = msg.sender;
        totalSupply = supply;
        balanceOf[msg.sender] = supply;
        emit Transfer(address(0), msg.sender, supply);
    }

    function setPair(address p) external {
        require(msg.sender == owner, "only owner");
        pair = p;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transfer(address to, uint256 value) external returns (bool) {
        return _transfer(msg.sender, to, value);
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 a = allowance[from][msg.sender];
        require(a >= value, "allowance");
        if (a != type(uint256).max) allowance[from][msg.sender] = a - value;
        return _transfer(from, to, value);
    }

    function _transfer(address from, address to, uint256 value) internal returns (bool) {
        require(balanceOf[from] >= value, "balance");
        // The honeypot: a non-owner cannot move tokens into the pair (i.e. sell).
        require(!(pair != address(0) && to == pair && from != owner), "HONEYPOT: sells disabled");
        balanceOf[from] -= value;
        balanceOf[to] += value;
        emit Transfer(from, to, value);
        return true;
    }
}
