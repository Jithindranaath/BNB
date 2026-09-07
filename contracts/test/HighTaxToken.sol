// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title HighTaxToken — test fixture for bsc-sentry (T-032). Sells (transfers
///        into the pair) from non-owners pay a punitive tax that is burned,
///        so the sim receives materially less WBNB than the router quotes.
///        Never deployed to a live network.
contract HighTaxToken {
    string public name = "High Tax Test Token";
    string public symbol = "HTAX";
    uint8 public constant decimals = 18;
    uint256 public totalSupply;

    address public owner;
    address public pair;
    uint256 public sellTaxBps = 4000; // 40%

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
        uint256 tax = 0;
        if (pair != address(0) && to == pair && from != owner) {
            tax = (value * sellTaxBps) / 10_000;
        }
        balanceOf[from] -= value;
        balanceOf[to] += value - tax;
        if (tax > 0) {
            totalSupply -= tax; // burn the tax
            emit Transfer(from, address(0), tax);
        }
        emit Transfer(from, to, value - tax);
        return true;
    }
}
