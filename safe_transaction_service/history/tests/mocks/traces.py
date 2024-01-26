from hexbytes import HexBytes

from gnosis.eth.tests.mocks.mock_internal_txs import creation_internal_txs  # noqa

create_trace = {
    "action": {
        "from": "0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B",
        "gas": 470747,
        "value": 0,
        "init": HexBytes(
            "0x608060405234801561001057600080fd5b506040516101e73803806101e78339818101604052602081101561003357600080fd5b8101908080519060200190929190505050600073ffffffffffffffffffffffffffffffffffffffff168173ffffffffffffffffffffffffffffffffffffffff1614156100ca576040517f08c379a00000000000000000000000000000000000000000000000000000000081526004018080602001828103825260248152602001806101c36024913960400191505060405180910390fd5b806000806101000a81548173ffffffffffffffffffffffffffffffffffffffff021916908373ffffffffffffffffffffffffffffffffffffffff1602179055505060aa806101196000396000f3fe608060405273ffffffffffffffffffffffffffffffffffffffff600054167fa619486e0000000000000000000000000000000000000000000000000000000060003514156050578060005260206000f35b3660008037600080366000845af43d6000803e60008114156070573d6000fd5b3d6000f3fea265627a7a72315820d8a00dc4fe6bf675a9d7416fc2d00bb3433362aa8186b750f76c4027269667ff64736f6c634300050e0032496e76616c6964206d617374657220636f707920616464726573732070726f766964656400000000000000000000000034cfac646f301356faa8b21e94227e3583fe3f5f"
        ),
    },
    "blockHash": "0x39ba45ad930dece3aec537c8c5cd615daf7ee39a2513475e7680ec226e90b923",
    "blockNumber": 6045252,
    "result": {
        "gasUsed": 55109,
        "code": HexBytes(
            "0x608060405273ffffffffffffffffffffffffffffffffffffffff600054167fa619486e0000000000000000000000000000000000000000000000000000000060003514156050578060005260206000f35b3660008037600080366000845af43d6000803e60008114156070573d6000fd5b3d6000f3fea265627a7a72315820d8a00dc4fe6bf675a9d7416fc2d00bb3433362aa8186b750f76c4027269667ff64736f6c634300050e0032"
        ),
        "address": "0x673Fd582FED2CD8201d58552B912F0D1DaA37bB2",
    },
    "subtraces": 0,
    "traceAddress": [],
    "transactionHash": "0x18f8eb25336203d4e561229c08a3a0ef88db1dd9767b641301d9ea3121dfeaea",
    "transactionPosition": 0,
    "type": "create",
}

call_trace = {
    "action": {
        "from": "0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B",
        "gas": 415719,
        "value": 0,
        "callType": "call",
        "input": HexBytes(
            "0xb63e800d0000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000140000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cdbdf440000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001000000000000000000000000198c09f30dba1494c741c510400cfe93b82875130000000000000000000000000000000000000000000000000000000000000000"
        ),
        "to": "0x673Fd582FED2CD8201d58552B912F0D1DaA37bB2",
    },
    "blockHash": "0x39ba45ad930dece3aec537c8c5cd615daf7ee39a2513475e7680ec226e90b923",
    "blockNumber": 6045252,
    "result": {"gasUsed": 150098, "output": HexBytes("0x")},
    "subtraces": 1,
    "traceAddress": [0],
    "transactionHash": "0x18f8eb25336203d4e561229c08a3a0ef88db1dd9767b641301d9ea3121dfeaea",
    "transactionPosition": 0,
    "type": "call",
}

testnet_traces = [
    {
        "action": {
            "from": "0x5aC255889882aCd3da2aA939679E3f3d4cea221e",
            "gas": 511126,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x61b69abd00000000000000000000000034cfac646f301356faa8b21e94227e3583fe3f5f00000000000000000000000000000000000000000000000000000000000000400000000000000000000000000000000000000000000000000000000000000164b63e800d0000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000140000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cdbdf4400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000010000000000000000000000005ac255889882acd3da2aa939679e3f3d4cea221e000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B",
        },
        "blockHash": "0x39ba45ad930dece3aec537c8c5cd615daf7ee39a2513475e7680ec226e90b923",
        "blockNumber": 6045252,
        "result": {
            "gasUsed": 240081,
            "output": HexBytes(
                "0x000000000000000000000000673fd582fed2cd8201d58552b912f0d1daa37bb2"
            ),
        },
        "subtraces": 2,
        "traceAddress": [],
        "transactionHash": "0x18f8eb25336203d4e561229c08a3a0ef88db1dd9767b641301d9ea3121dfeaea",
        "transactionPosition": 0,
        "type": "call",
    },
    {
        "action": {
            "from": "0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B",
            "gas": 470747,
            "value": 0,
            "init": HexBytes(
                "0x608060405234801561001057600080fd5b506040516101e73803806101e78339818101604052602081101561003357600080fd5b8101908080519060200190929190505050600073ffffffffffffffffffffffffffffffffffffffff168173ffffffffffffffffffffffffffffffffffffffff1614156100ca576040517f08c379a00000000000000000000000000000000000000000000000000000000081526004018080602001828103825260248152602001806101c36024913960400191505060405180910390fd5b806000806101000a81548173ffffffffffffffffffffffffffffffffffffffff021916908373ffffffffffffffffffffffffffffffffffffffff1602179055505060aa806101196000396000f3fe608060405273ffffffffffffffffffffffffffffffffffffffff600054167fa619486e0000000000000000000000000000000000000000000000000000000060003514156050578060005260206000f35b3660008037600080366000845af43d6000803e60008114156070573d6000fd5b3d6000f3fea265627a7a72315820d8a00dc4fe6bf675a9d7416fc2d00bb3433362aa8186b750f76c4027269667ff64736f6c634300050e0032496e76616c6964206d617374657220636f707920616464726573732070726f766964656400000000000000000000000034cfac646f301356faa8b21e94227e3583fe3f5f"
            ),
        },
        "blockHash": "0x39ba45ad930dece3aec537c8c5cd615daf7ee39a2513475e7680ec226e90b923",
        "blockNumber": 6045252,
        "result": {
            "gasUsed": 55109,
            "code": HexBytes(
                "0x608060405273ffffffffffffffffffffffffffffffffffffffff600054167fa619486e0000000000000000000000000000000000000000000000000000000060003514156050578060005260206000f35b3660008037600080366000845af43d6000803e60008114156070573d6000fd5b3d6000f3fea265627a7a72315820d8a00dc4fe6bf675a9d7416fc2d00bb3433362aa8186b750f76c4027269667ff64736f6c634300050e0032"
            ),
            "address": "0x673Fd582FED2CD8201d58552B912F0D1DaA37bB2",
        },
        "subtraces": 0,
        "traceAddress": [0],
        "transactionHash": "0x18f8eb25336203d4e561229c08a3a0ef88db1dd9767b641301d9ea3121dfeaea",
        "transactionPosition": 0,
        "type": "create",
    },
    {
        "action": {
            "from": "0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B",
            "gas": 415719,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xb63e800d0000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000140000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cdbdf4400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000010000000000000000000000005ac255889882acd3da2aa939679e3f3d4cea221e0000000000000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x673Fd582FED2CD8201d58552B912F0D1DaA37bB2",
        },
        "blockHash": "0x39ba45ad930dece3aec537c8c5cd615daf7ee39a2513475e7680ec226e90b923",
        "blockNumber": 6045252,
        "result": {"gasUsed": 150098, "output": HexBytes("0x")},
        "subtraces": 1,
        "traceAddress": [1],
        "transactionHash": "0x18f8eb25336203d4e561229c08a3a0ef88db1dd9767b641301d9ea3121dfeaea",
        "transactionPosition": 0,
        "type": "call",
    },
    {
        "action": {
            "from": "0x673Fd582FED2CD8201d58552B912F0D1DaA37bB2",
            "gas": 407604,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0xb63e800d0000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000140000000000000000000000000d5d82b6addc9027b22dca772aa68d5d74cdbdf4400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000010000000000000000000000005ac255889882acd3da2aa939679e3f3d4cea221e0000000000000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F",
        },
        "blockHash": "0x39ba45ad930dece3aec537c8c5cd615daf7ee39a2513475e7680ec226e90b923",
        "blockNumber": 6045252,
        "result": {"gasUsed": 148410, "output": HexBytes("0x")},
        "subtraces": 0,
        "traceAddress": [1, 0],
        "transactionHash": "0x18f8eb25336203d4e561229c08a3a0ef88db1dd9767b641301d9ea3121dfeaea",
        "transactionPosition": 0,
        "type": "call",
    },
]  # Taken from Rinkeby

module_traces = [
    {
        "action": {
            "from": "0x32cA2c42e3CA59f5785711dc81Ae92ea99FB763e",
            "gas": 7978200,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x1068361f0000000000000000000000000411cd48bb8f5a29eb2e5917df40521b70902ff6000000000000000000000000beb32aa1b171acf79951c4e96e0312f85e1e8ad6"
            ),
            "to": "0x713D07E8F9F7D1D6FA486dFc152E419b9DfD954e",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 878006, "output": HexBytes("0x")},
        "subtraces": 8,
        "traceAddress": [],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x713D07E8F9F7D1D6FA486dFc152E419b9DfD954e",
            "gas": 7847083,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x95a2251f0000000000000000000000006b175474e89094c44da98b954eedeac495271d0f"
            ),
            "to": "0x03967E5b71577ba3498E1a87E425139B22B3c085",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 369851, "output": HexBytes("0x")},
        "subtraces": 1,
        "traceAddress": [0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x03967E5b71577ba3498E1a87E425139B22B3c085",
            "gas": 7722909,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x95a2251f0000000000000000000000006b175474e89094c44da98b954eedeac495271d0f"
            ),
            "to": "0xe657230ee18aAFAD1fcdBAE1eefFa90e07b46dc5",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 368220, "output": HexBytes("0x")},
        "subtraces": 5,
        "traceAddress": [0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x03967E5b71577ba3498E1a87E425139B22B3c085",
            "gas": 7599629,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x2f54bf6e000000000000000000000000713d07e8f9f7d1d6fa486dfc152e419b9dfd954e"
            ),
            "to": "0x1f8eaD1e6e10e6856d68be2217EDDC71D8b4eC87",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 2991,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 1,
        "traceAddress": [0, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x1f8eaD1e6e10e6856d68be2217EDDC71D8b4eC87",
            "gas": 7479321,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x2f54bf6e000000000000000000000000713d07e8f9f7d1d6fa486dfc152e419b9dfd954e"
            ),
            "to": "0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1357,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x03967E5b71577ba3498E1a87E425139B22B3c085",
            "gas": 7592242,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x70a082310000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec87"
            ),
            "to": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 7326,
            "output": HexBytes(
                "0x00000000000000000000000000000000000000000000000000012c64767da069"
            ),
        },
        "subtraces": 1,
        "traceAddress": [0, 0, 1],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 7471272,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x0933c1ed0000000000000000000000000000000000000000000000000000000000000020000000000000000000000000000000000000000000000000000000000000002470a082310000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec8700000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 4210,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000020000000000000000000000000000000000000000000000000000000000000002000000000000000000000000000000000000000000000000000012c64767da069"
            ),
        },
        "subtraces": 1,
        "traceAddress": [0, 0, 1, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 7352083,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x70a082310000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec87"
            ),
            "to": "0xbB8bE4772fAA655C255309afc3c5207aA7b896Fd",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1253,
            "output": HexBytes(
                "0x00000000000000000000000000000000000000000000000000012c64767da069"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 1, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x03967E5b71577ba3498E1a87E425139B22B3c085",
            "gas": 7581011,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x468721a70000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e36430000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000024db006a7500000000000000000000000000000000000000000000000000012c64767da06900000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x1f8eaD1e6e10e6856d68be2217EDDC71D8b4eC87",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 304707,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 1,
        "traceAddress": [0, 0, 2],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x1f8eaD1e6e10e6856d68be2217EDDC71D8b4eC87",
            "gas": 7460962,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x468721a70000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e36430000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000024db006a7500000000000000000000000000000000000000000000000000012c64767da06900000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 303040,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 1,
        "traceAddress": [0, 0, 2, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x1f8eaD1e6e10e6856d68be2217EDDC71D8b4eC87",
            "gas": 7341831,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xdb006a7500000000000000000000000000000000000000000000000000012c64767da069"
            ),
            "to": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 299095,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
            ),
        },
        "subtraces": 1,
        "traceAddress": [0, 0, 2, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 7224785,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0xdb006a7500000000000000000000000000000000000000000000000000012c64767da069"
            ),
            "to": "0xbB8bE4772fAA655C255309afc3c5207aA7b896Fd",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 296414,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
            ),
        },
        "subtraces": 13,
        "traceAddress": [0, 0, 2, 0, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 7102747,
            "value": 0,
            "callType": "call",
            "input": HexBytes("0x9f678cca"),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 33074,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000034a13ac9ed2cf6900e592bb"
            ),
        },
        "subtraces": 1,
        "traceAddress": [0, 0, 2, 0, 0, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
            "gas": 6976128,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xf24e23eb000000000000000000000000a950524441892a31ebddf91d3ceefa04bf454466000000000000000000000000197e90f9fad81970ba7976f33cbd77088e5d7cf70000000000000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x35D1b3F3D7966A1DFe207aa4514C12a259A0492B",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 12764, "output": HexBytes("0x")},
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 7067461,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x0bebac860000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643"
            ),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1215,
            "output": HexBytes(
                "0x000000000000000000000000000000000000000000c3135bd08061bcc1424a7a"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 1],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 7064662,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes("0xc92aecc4"),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1093,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000034a13ac9ed2cf6900e592bb"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 2],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 7059396,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x15f24053000000000000000000000000000000000000000000c696b0665921cd67e40da4000000000000000000000000000000000000000002a67c2fb2ae20bc971bd3d4000000000000000000000000000000000000000000007c61301c409f4eace0c4"
            ),
            "to": "0xfeD941d39905B23D6FAf02C8301d40bD4834E27F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 3881,
            "output": HexBytes(
                "0x00000000000000000000000000000000000000000000000000000004492f33e2"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 3],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 7021182,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x0bebac860000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643"
            ),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1215,
            "output": HexBytes(
                "0x000000000000000000000000000000000000000000c3135bd08061bcc1424a7a"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 4],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 7018384,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes("0xc92aecc4"),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1093,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000034a13ac9ed2cf6900e592bb"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 5],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 7010175,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xeabe7d910000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e36430000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec8700000000000000000000000000000000000000000000000000012c64767da069"
            ),
            "to": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 63041,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
            ),
        },
        "subtraces": 1,
        "traceAddress": [0, 0, 2, 0, 0, 0, 6],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
            "gas": 6898850,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0xeabe7d910000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e36430000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec8700000000000000000000000000000000000000000000000000012c64767da069"
            ),
            "to": "0x7b5e3521a049C8fF88e6349f33044c6Cc33c113c",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 61051,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
            ),
        },
        "subtraces": 4,
        "traceAddress": [0, 0, 2, 0, 0, 0, 6, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
            "gas": 6785170,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes("0x18160ddd"),
            "to": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1044,
            "output": HexBytes(
                "0x00000000000000000000000000000000000000000000000047258ec1eb814b75"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 6, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
            "gas": 6766457,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x70a082310000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec87"
            ),
            "to": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 7326,
            "output": HexBytes(
                "0x00000000000000000000000000000000000000000000000000012c64767da069"
            ),
        },
        "subtraces": 1,
        "traceAddress": [0, 0, 2, 0, 0, 0, 6, 0, 1],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6658390,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x0933c1ed0000000000000000000000000000000000000000000000000000000000000020000000000000000000000000000000000000000000000000000000000000002470a082310000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec8700000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 4210,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000020000000000000000000000000000000000000000000000000000000000000002000000000000000000000000000000000000000000000000000012c64767da069"
            ),
        },
        "subtraces": 1,
        "traceAddress": [0, 0, 2, 0, 0, 0, 6, 0, 1, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6551902,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x70a082310000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec87"
            ),
            "to": "0xbB8bE4772fAA655C255309afc3c5207aA7b896Fd",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1253,
            "output": HexBytes(
                "0x00000000000000000000000000000000000000000000000000012c64767da069"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 6, 0, 1, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
            "gas": 6756065,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x70a082310000000000000000000000003d9819210a31b4961b30ef54be2aed79b9c9cd3b"
            ),
            "to": "0xc00e94Cb662C3520282E6f5717214004A7f26888",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1488,
            "output": HexBytes(
                "0x000000000000000000000000000000000000000000000d0c7e14bee79dde12f6"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 6, 0, 2],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
            "gas": 6752929,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xa9059cbb0000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec870000000000000000000000000000000000000000000000000076b3dd96692b80"
            ),
            "to": "0xc00e94Cb662C3520282E6f5717214004A7f26888",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 19090,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 6, 0, 3],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6942647,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x0bebac860000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643"
            ),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1215,
            "output": HexBytes(
                "0x000000000000000000000000000000000000000000c3135bd08061bcc1424a7a"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 7],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6939848,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes("0xc92aecc4"),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1093,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000034a13ac9ed2cf6900e592bb"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 8],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6935366,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes("0xc92aecc4"),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1093,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000034a13ac9ed2cf6900e592bb"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 9],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6932482,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x7f8661a1000000000000000000000000000000000000000000000e339e52688f4d37943b"
            ),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 37936, "output": HexBytes("0x")},
        "subtraces": 1,
        "traceAddress": [0, 0, 2, 0, 0, 0, 10],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
            "gas": 6808782,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xbb35783b000000000000000000000000197e90f9fad81970ba7976f33cbd77088e5d7cf70000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e364300000000000000000000002eb6de2349f20528301144cfa5cd11aea1b2e9ed19"
            ),
            "to": "0x35D1b3F3D7966A1DFe207aa4514C12a259A0492B",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 17943, "output": HexBytes("0x")},
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 10, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6893535,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xef693bed0000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec87000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0x9759A6Ac90977b93B58547b4A71c78317f391A28",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 54301, "output": HexBytes("0x")},
        "subtraces": 2,
        "traceAddress": [0, 0, 2, 0, 0, 0, 11],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x9759A6Ac90977b93B58547b4A71c78317f391A28",
            "gas": 6782168,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xbb35783b0000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e36430000000000000000000000009759a6ac90977b93b58547b4a71c78317f391a2800000000000000000000002eb6de2349f20528300fea91f45de97c1238000000"
            ),
            "to": "0x35D1b3F3D7966A1DFe207aa4514C12a259A0492B",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 13743, "output": HexBytes("0x")},
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 11, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x9759A6Ac90977b93B58547b4A71c78317f391A28",
            "gas": 6766249,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x40c10f190000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec87000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 30045, "output": HexBytes("0x")},
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 11, 1],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6824198,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x51dff9890000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e36430000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec87000000000000000000000000000000000000000000000e75171d9d298328963300000000000000000000000000000000000000000000000000012c64767da069"
            ),
            "to": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 2359, "output": HexBytes("0x")},
        "subtraces": 1,
        "traceAddress": [0, 0, 2, 0, 0, 0, 12],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
            "gas": 6715783,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x51dff9890000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e36430000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec87000000000000000000000000000000000000000000000e75171d9d298328963300000000000000000000000000000000000000000000000000012c64767da069"
            ),
            "to": "0x7b5e3521a049C8fF88e6349f33044c6Cc33c113c",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 446, "output": HexBytes("0x")},
        "subtraces": 0,
        "traceAddress": [0, 0, 2, 0, 0, 0, 12, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x03967E5b71577ba3498E1a87E425139B22B3c085",
            "gas": 7278548,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x70a082310000000000000000000000001f8ead1e6e10e6856d68be2217eddc71d8b4ec87"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1302,
            "output": HexBytes(
                "0x000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 3],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x03967E5b71577ba3498E1a87E425139B22B3c085",
            "gas": 7274059,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x468721a70000000000000000000000006b175474e89094c44da98b954eedeac495271d0f0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000044a9059cbb000000000000000000000000713d07e8f9f7d1d6fa486dfc152e419b9dfd954e000000000000000000000000000000000000000000000e75171d9d298328963300000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x1f8eaD1e6e10e6856d68be2217EDDC71D8b4eC87",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 31798,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 1,
        "traceAddress": [0, 0, 4],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x1f8eaD1e6e10e6856d68be2217EDDC71D8b4eC87",
            "gas": 7158800,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x468721a70000000000000000000000006b175474e89094c44da98b954eedeac495271d0f0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000044a9059cbb000000000000000000000000713d07e8f9f7d1d6fa486dfc152e419b9dfd954e000000000000000000000000000000000000000000000e75171d9d298328963300000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 30125,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 1,
        "traceAddress": [0, 0, 4, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x1f8eaD1e6e10e6856d68be2217EDDC71D8b4eC87",
            "gas": 7044384,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xa9059cbb000000000000000000000000713d07e8f9f7d1d6fa486dfc152e419b9dfd954e000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 26174,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 0,
        "traceAddress": [0, 0, 4, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x713D07E8F9F7D1D6FA486dFc152E419b9DfD954e",
            "gas": 7479805,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x70a08231000000000000000000000000713d07e8f9f7d1d6fa486dfc152e419b9dfd954e"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1302,
            "output": HexBytes(
                "0x000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
        },
        "subtraces": 0,
        "traceAddress": [1],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x713D07E8F9F7D1D6FA486dFc152E419b9DfD954e",
            "gas": 7476893,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xa9059cbb0000000000000000000000000411cd48bb8f5a29eb2e5917df40521b70902ff6000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 26174,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 0,
        "traceAddress": [2],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x713D07E8F9F7D1D6FA486dFc152E419b9DfD954e",
            "gas": 7447843,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x70a08231000000000000000000000000713d07e8f9f7d1d6fa486dfc152e419b9dfd954e"
            ),
            "to": "0xF81beb4d26F4517Bd413184f700Fb3D8c138d274",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1241,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000de0b6b3a7640000"
            ),
        },
        "subtraces": 0,
        "traceAddress": [3],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x713D07E8F9F7D1D6FA486dFc152E419b9DfD954e",
            "gas": 7444993,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xa9059cbb0000000000000000000000000411cd48bb8f5a29eb2e5917df40521b70902ff60000000000000000000000000000000000000000000000000de0b6b3a7640000"
            ),
            "to": "0xF81beb4d26F4517Bd413184f700Fb3D8c138d274",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 29691,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 0,
        "traceAddress": [4],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x713D07E8F9F7D1D6FA486dFc152E419b9DfD954e",
            "gas": 7413315,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xb3ab15fb0000000000000000000000000411cd48bb8f5a29eb2e5917df40521b70902ff6"
            ),
            "to": "0xF81beb4d26F4517Bd413184f700Fb3D8c138d274",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 9192, "output": HexBytes("0x")},
        "subtraces": 0,
        "traceAddress": [5],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x713D07E8F9F7D1D6FA486dFc152E419b9DfD954e",
            "gas": 7402698,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xf46d1982000000000000000000000000beb32aa1b171acf79951c4e96e0312f85e1e8ad60000000000000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x0411CD48Bb8F5a29EB2E5917Df40521b70902FF6",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 403530, "output": HexBytes("0x")},
        "subtraces": 3,
        "traceAddress": [6],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x0411CD48Bb8F5a29EB2E5917Df40521b70902FF6",
            "gas": 7261947,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x095ea7b3000000000000000000000000beb32aa1b171acf79951c4e96e0312f85e1e8ad6ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 22414,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x0411CD48Bb8F5a29EB2E5917Df40521b70902FF6",
            "gas": 7236667,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x70a082310000000000000000000000000411cd48bb8f5a29eb2e5917df40521b70902ff6"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1302,
            "output": HexBytes(
                "0x000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 1],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x0411CD48Bb8F5a29EB2E5917Df40521b70902FF6",
            "gas": 7233755,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x47e7ef240000000000000000000000006b175474e89094c44da98b954eedeac495271d0f000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0xbEb32Aa1B171Acf79951c4E96E0312F85E1E8Ad6",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 348011, "output": HexBytes("0x")},
        "subtraces": 1,
        "traceAddress": [6, 2],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0xbEb32Aa1B171Acf79951c4E96E0312F85E1E8Ad6",
            "gas": 7119161,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x47e7ef240000000000000000000000006b175474e89094c44da98b954eedeac495271d0f000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0x43C28c50abF19D448E3E8286583799c128f2cC38",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 346377, "output": HexBytes("0x")},
        "subtraces": 4,
        "traceAddress": [6, 2, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0xbEb32Aa1B171Acf79951c4E96E0312F85E1E8Ad6",
            "gas": 7005138,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x2f54bf6e0000000000000000000000000411cd48bb8f5a29eb2e5917df40521b70902ff6"
            ),
            "to": "0x6Ea7a9EE186552559Ceeca4F98167ae2D29148B6",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 2991,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 1,
        "traceAddress": [6, 2, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x6Ea7a9EE186552559Ceeca4F98167ae2D29148B6",
            "gas": 6894119,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x2f54bf6e0000000000000000000000000411cd48bb8f5a29eb2e5917df40521b70902ff6"
            ),
            "to": "0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1357,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0xbEb32Aa1B171Acf79951c4E96E0312F85E1E8Ad6",
            "gas": 6998516,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x23b872dd0000000000000000000000000411cd48bb8f5a29eb2e5917df40521b70902ff60000000000000000000000006ea7a9ee186552559ceeca4f98167ae2d29148b6000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 27218,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 1],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0xbEb32Aa1B171Acf79951c4E96E0312F85E1E8Ad6",
            "gas": 6967485,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x468721a70000000000000000000000006b175474e89094c44da98b954eedeac495271d0f0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000044095ea7b30000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643000000000000000000000000000000000000000000000e75171d9d298328963300000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x6Ea7a9EE186552559Ceeca4F98167ae2D29148B6",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 28038,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 1,
        "traceAddress": [6, 2, 0, 2],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x6Ea7a9EE186552559Ceeca4F98167ae2D29148B6",
            "gas": 6857016,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x468721a70000000000000000000000006b175474e89094c44da98b954eedeac495271d0f0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000044095ea7b30000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643000000000000000000000000000000000000000000000e75171d9d298328963300000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 26365,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 1,
        "traceAddress": [6, 2, 0, 2, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x6Ea7a9EE186552559Ceeca4F98167ae2D29148B6",
            "gas": 6747315,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x095ea7b30000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 22414,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 2, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0xbEb32Aa1B171Acf79951c4E96E0312F85E1E8Ad6",
            "gas": 6935748,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x468721a70000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e36430000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000024a0712d68000000000000000000000000000000000000000000000e75171d9d298328963300000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x6Ea7a9EE186552559Ceeca4F98167ae2D29148B6",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 270176,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 1,
        "traceAddress": [6, 2, 0, 3],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x6Ea7a9EE186552559Ceeca4F98167ae2D29148B6",
            "gas": 6825781,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x468721a70000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e36430000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000008000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000024a0712d68000000000000000000000000000000000000000000000e75171d9d298328963300000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 268509,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 1,
        "traceAddress": [6, 2, 0, 3, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x6Ea7a9EE186552559Ceeca4F98167ae2D29148B6",
            "gas": 6716574,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xa0712d68000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 264564,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
            ),
        },
        "subtraces": 1,
        "traceAddress": [6, 2, 0, 3, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6609254,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0xa0712d68000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0xbB8bE4772fAA655C255309afc3c5207aA7b896Fd",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 261838,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
            ),
        },
        "subtraces": 16,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6496824,
            "value": 0,
            "callType": "call",
            "input": HexBytes("0x9f678cca"),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 27669,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000034a13ac9ed2cf6900e592bb"
            ),
        },
        "subtraces": 1,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
            "gas": 6384993,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xf24e23eb000000000000000000000000a950524441892a31ebddf91d3ceefa04bf454466000000000000000000000000197e90f9fad81970ba7976f33cbd77088e5d7cf70000000000000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x35D1b3F3D7966A1DFe207aa4514C12a259A0492B",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 12764, "output": HexBytes("0x")},
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6466858,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x0bebac860000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643"
            ),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1215,
            "output": HexBytes(
                "0x000000000000000000000000000000000000000000c30528322df92d740ab63f"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 1],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6464059,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes("0xc92aecc4"),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1093,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000034a13ac9ed2cf6900e592bb"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 2],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6458793,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x15f24053000000000000000000000000000000000000000000c6883b4f3b84a3e4bb7770000000000000000000000000000000000000000002a67c3710824510a165c528000000000000000000000000000000000000000000007c618e66dc09e8ca2cd5"
            ),
            "to": "0xfeD941d39905B23D6FAf02C8301d40bD4834E27F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 3881,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000449414fd1"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 3],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6438260,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x4ef4c3e10000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e36430000000000000000000000006ea7a9ee186552559ceeca4f98167ae2d29148b6000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 42498,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
            ),
        },
        "subtraces": 1,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 4],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
            "gas": 6335881,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x4ef4c3e10000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e36430000000000000000000000006ea7a9ee186552559ceeca4f98167ae2d29148b6000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0x7b5e3521a049C8fF88e6349f33044c6Cc33c113c",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 40518,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
            ),
        },
        "subtraces": 1,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 4, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
            "gas": 6208839,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x70a082310000000000000000000000006ea7a9ee186552559ceeca4f98167ae2d29148b6"
            ),
            "to": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 7326,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
            ),
        },
        "subtraces": 1,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 4, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6109485,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x0933c1ed0000000000000000000000000000000000000000000000000000000000000020000000000000000000000000000000000000000000000000000000000000002470a082310000000000000000000000006ea7a9ee186552559ceeca4f98167ae2d29148b600000000000000000000000000000000000000000000000000000000"
            ),
            "to": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 4210,
            "output": HexBytes(
                "0x000000000000000000000000000000000000000000000000000000000000002000000000000000000000000000000000000000000000000000000000000000200000000000000000000000000000000000000000000000000000000000000000"
            ),
        },
        "subtraces": 1,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 4, 0, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6011574,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x70a082310000000000000000000000006ea7a9ee186552559ceeca4f98167ae2d29148b6"
            ),
            "to": "0xbB8bE4772fAA655C255309afc3c5207aA7b896Fd",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1253,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 4, 0, 0, 0, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6392940,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0xdd62ed3e0000000000000000000000006ea7a9ee186552559ceeca4f98167ae2d29148b60000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1377,
            "output": HexBytes(
                "0x000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 5],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6389943,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x70a082310000000000000000000000006ea7a9ee186552559ceeca4f98167ae2d29148b6"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1302,
            "output": HexBytes(
                "0x000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 6],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6385243,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x0bebac860000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643"
            ),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1215,
            "output": HexBytes(
                "0x000000000000000000000000000000000000000000c30528322df92d740ab63f"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 7],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6382445,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes("0xc92aecc4"),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1093,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000034a13ac9ed2cf6900e592bb"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 8],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6375095,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x23b872dd0000000000000000000000006ea7a9ee186552559ceeca4f98167ae2d29148b60000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 30275,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 9],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6340455,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x70a082310000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1302,
            "output": HexBytes(
                "0x000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 10],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6337544,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x3b4da69f0000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0x9759A6Ac90977b93B58547b4A71c78317f391A28",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 26936, "output": HexBytes("0x")},
        "subtraces": 2,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 11],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x9759A6Ac90977b93B58547b4A71c78317f391A28",
            "gas": 6235716,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xbb35783b0000000000000000000000009759a6ac90977b93b58547b4a71c78317f391a280000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e364300000000000000000000002eb6de2349f20528300fea91f45de97c1238000000"
            ),
            "to": "0x35D1b3F3D7966A1DFe207aa4514C12a259A0492B",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 9543, "output": HexBytes("0x")},
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 11, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x9759A6Ac90977b93B58547b4A71c78317f391A28",
            "gas": 6223932,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x9dc29fac0000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643000000000000000000000000000000000000000000000e75171d9d2983289633"
            ),
            "to": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 7746, "output": HexBytes("0x")},
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 11, 1],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6309464,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes(
                "0x6c25b3460000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643"
            ),
            "to": "0x35D1b3F3D7966A1DFe207aa4514C12a259A0492B",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1236,
            "output": HexBytes(
                "0x00000000000000000000002eb6de2349f20528301464be242dca461ce1baabfa"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 12],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6306654,
            "value": 0,
            "callType": "staticcall",
            "input": HexBytes("0xc92aecc4"),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {
            "gasUsed": 1093,
            "output": HexBytes(
                "0x0000000000000000000000000000000000000000034a13ac9ed2cf6900e592bb"
            ),
        },
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 13],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6303962,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x049878f3000000000000000000000000000000000000000000000e339e52688f4d37943b"
            ),
            "to": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 21915, "output": HexBytes("0x")},
        "subtraces": 1,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 14],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7",
            "gas": 6197584,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xbb35783b0000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e3643000000000000000000000000197e90f9fad81970ba7976f33cbd77088e5d7cf700000000000000000000002eb6de2349f20528301144cfa5cd11aea1b2e9ed19"
            ),
            "to": "0x35D1b3F3D7966A1DFe207aa4514C12a259A0492B",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 9543, "output": HexBytes("0x")},
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 14, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x5d3a536E4D6DbD6114cc1Ead35777bAB948E3643",
            "gas": 6252318,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0x41c728b90000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e36430000000000000000000000006ea7a9ee186552559ceeca4f98167ae2d29148b6000000000000000000000000000000000000000000000e75171d9d298328963300000000000000000000000000000000000000000000000000012c64767da068"
            ),
            "to": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 2316, "output": HexBytes("0x")},
        "subtraces": 1,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 15],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
            "gas": 6152838,
            "value": 0,
            "callType": "delegatecall",
            "input": HexBytes(
                "0x41c728b90000000000000000000000005d3a536e4d6dbd6114cc1ead35777bab948e36430000000000000000000000006ea7a9ee186552559ceeca4f98167ae2d29148b6000000000000000000000000000000000000000000000e75171d9d298328963300000000000000000000000000000000000000000000000000012c64767da068"
            ),
            "to": "0x7b5e3521a049C8fF88e6349f33044c6Cc33c113c",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 403, "output": HexBytes("0x")},
        "subtraces": 0,
        "traceAddress": [6, 2, 0, 3, 0, 0, 0, 15, 0],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
    {
        "action": {
            "from": "0x713D07E8F9F7D1D6FA486dFc152E419b9DfD954e",
            "gas": 7003102,
            "value": 0,
            "callType": "call",
            "input": HexBytes(
                "0xb3ab15fb00000000000000000000000032ca2c42e3ca59f5785711dc81ae92ea99fb763e"
            ),
            "to": "0x0411CD48Bb8F5a29EB2E5917Df40521b70902FF6",
        },
        "blockHash": "0xb7a05f742a05f324256950f8e871587fbb1d866f60cffbfde2f07f7170544b96",
        "blockNumber": 10913066,
        "result": {"gasUsed": 8156, "output": HexBytes("0x")},
        "subtraces": 0,
        "traceAddress": [7],
        "transactionHash": "0x59f20a56a94ad4ee934468eb26b9148151289c97fefece779e05d98befd156f0",
        "transactionPosition": 15,
        "type": "call",
    },
]
