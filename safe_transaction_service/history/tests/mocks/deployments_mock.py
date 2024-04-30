mainnet_deployments_1_4_1_multisend = {
    "contractName": "MultiSend",
    "address": "0x38869bf66a61cF6bDB996A6aE40D5853Fd43B526",
}

mainnet_deployments_1_4_1_safe = {
    "contractName": "Safe",
    "address": "0x41675C099F32341bf84BFc5382aF534df5C7461a",
}

mainnet_deployments_1_4_1 = {
    "version": "1.4.1",
    "contracts": [
        {
            "contractName": "CompatibilityFallbackHandler",
            "address": "0xfd0732Dc9E303f09fCEf3a7388Ad10A83459Ec99",
        },
        {
            "contractName": "CreateCall",
            "address": "0x9b35Af71d77eaf8d7e40252370304687390A1A52",
        },
        mainnet_deployments_1_4_1_multisend,
        {
            "contractName": "MultiSendCallOnly",
            "address": "0x9641d764fc13c8B624c04430C7356C1C7C8102e2",
        },
        mainnet_deployments_1_4_1_safe,
        {
            "contractName": "SafeL2",
            "address": "0x29fcB43b46531BcA003ddC8FCB67FFE91900C762",
        },
        {
            "contractName": "SafeProxyFactory",
            "address": "0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67",
        },
        {
            "contractName": "SignMessageLib",
            "address": "0xd53cd0aB83D845Ac265BE939c57F53AD838012c9",
        },
        {
            "contractName": "SimulateTxAccessor",
            "address": "0x3d4BA2E0884aa488718476ca2FB8Efc291A46199",
        },
    ],
}

mainnet_deployments_1_3_0 = {
    "version": "1.3.0",
    "contracts": [
        {
            "contractName": "CompatibilityFallbackHandler",
            "address": "0xf48f2B2d2a534e402487b3ee7C18c33Aec0Fe5e4",
        },
        {
            "contractName": "CreateCall",
            "address": "0x7cbB62EaA69F79e6873cD1ecB2392971036cFAa4",
        },
        {
            "contractName": "GnosisSafe",
            "address": "0xd9Db270c1B5E3Bd161E8c8503c55cEABeE709552",
        },
        {
            "contractName": "GnosisSafeL2",
            "address": "0x3E5c63644E683549055b9Be8653de26E0B4CD36E",
        },
        {
            "contractName": "MultiSend",
            "address": "0xA238CBeb142c10Ef7Ad8442C6D1f9E89e07e7761",
        },
        {
            "contractName": "MultiSendCallOnly",
            "address": "0x40A2aCCbd92BCA938b02010E17A5b8929b49130D",
        },
        {
            "contractName": "GnosisSafeProxyFactory",
            "address": "0xa6B71E26C5e0845f74c812102Ca7114b6a896AB2",
        },
        {
            "contractName": "SignMessageLib",
            "address": "0xA65387F16B013cf2Af4605Ad8aA5ec25a2cbA3a2",
        },
        {
            "contractName": "SimulateTxAccessor",
            "address": "0x59AD6735bCd8152B84860Cb256dD9e96b85F69Da",
        },
    ],
}

mainnet_deployments_1_2_0 = {
    "version": "1.2.0",
    "contracts": [
        {
            "contractName": "GnosisSafe",
            "address": "0x6851D6fDFAfD08c0295C392436245E5bc78B0185",
        }
    ],
}

mainnet_deployments_1_1_1 = {
    "version": "1.1.1",
    "contracts": [
        {
            "contractName": "CreateAndAddModules",
            "address": "0xF61A721642B0c0C8b334bA3763BA1326F53798C0",
        },
        {
            "contractName": "CreateCall",
            "address": "0x8538FcBccba7f5303d2C679Fa5d7A629A8c9bf4A",
        },
        {
            "contractName": "DefaultCallbackHandler",
            "address": "0xd5D82B6aDDc9027B22dCA772Aa68D5d74cdBdF44",
        },
        {
            "contractName": "GnosisSafe",
            "address": "0x34CfAC646f301356fAa8B21e94227e3583Fe3F5F",
        },
        {
            "contractName": "MultiSend",
            "address": "0x8D29bE29923b68abfDD21e541b9374737B49cdAD",
        },
        {
            "contractName": "ProxyFactory",
            "address": "0x76E2cFc1F5Fa8F6a5b3fC4c8F4788F0116861F9B",
        },
    ],
}

mainnet_deployments_1_0_0 = {
    "version": "1.0.0",
    "contracts": [
        {
            "contractName": "GnosisSafe",
            "address": "0xb6029EA3B2c51D09a50B53CA8012FeEB05bDa35A",
        },
        {
            "contractName": "ProxyFactory",
            "address": "0x12302fE9c02ff50939BaAaaf415fc226C078613C",
        },
    ],
}

mainnet_deployments = [
    mainnet_deployments_1_0_0,
    mainnet_deployments_1_1_1,
    mainnet_deployments_1_2_0,
    mainnet_deployments_1_3_0,
    mainnet_deployments_1_4_1,
]
